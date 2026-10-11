import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import disparar  # noqa: E402
import issues  # noqa: E402
import portao  # noqa: E402
import relatorio  # noqa: E402

REPORT = {
    "issue": 12,
    "publicado": [{"caminho": "tables/tru.2027-01-01.json", "titulo": "TRU 2027", "vigencia": "2027-01-01",
                   "fontes": ["Decreto-Lei n.º 9/2027 — https://diariodarepublica.pt/x"]}],
    "precisaDeTi": [{"titulo": "Carreira de TSDT com níveis novos", "texto": "O DL muda as posições.", "fontes": []}],
    "semAlteracoes": [{"pista": "Despacho n.º 2/2027", "motivo": "subdelegação de competências"}],
}


class PortaoTest(unittest.TestCase):
    def test_data_and_one_report_pass(self):
        problems, reports = portao.problems([("A", "tables/tru.2027-01-01.json"), ("M", "manifest.json"),
                                             ("M", "VERIFICAR.md"), ("A", "relatorios/2027-01-31.json")])
        self.assertEqual(problems, [])
        self.assertEqual(reports, ["relatorios/2027-01-31.json"])

    def test_tools_github_and_rotina_are_refused(self):
        problems, _ = portao.problems([("M", "tools/plausivel.py"), ("M", ".github/workflows/publicar.yml"),
                                       ("M", "ROTINA.md"), ("A", "relatorios/2027-01-31.json")])
        self.assertEqual(len(problems), 3)

    def test_deleting_a_table_is_refused(self):
        problems, _ = portao.problems([("D", "tables/tru.2026-01-01.json"), ("A", "relatorios/2027-01-31.json")])
        self.assertTrue(any("apagar" in p for p in problems))

    def test_exactly_one_new_report(self):
        problems, _ = portao.problems([("A", "tables/tru.2027-01-01.json")])
        self.assertTrue(any("exatamente um relatório" in p for p in problems))

    def test_only_added_or_modified_statuses_pass(self):
        for status in ("T", "U", "X", "C", ""):
            problems, _ = portao.problems([(status, "tables/tru.2026-01-01.json"), ("A", "relatorios/2027-01-31.json")])
            self.assertTrue(problems, status)

    def test_only_json_tables_and_taxes(self):
        problems, _ = portao.problems([("A", "tables/run.sh"), ("A", "tax/x.py"), ("A", "relatorios/2027-01-31.json")])
        self.assertEqual(len(problems), 2)

    def test_report_must_be_a_new_json_file_directly_in_relatorios(self):
        for changes in ([("M", "relatorios/2027-01-31.json")],
                        [("A", "relatorios/sub/r.json")],
                        [("A", "relatorios/r.txt")],
                        [("A", "relatorios/2027-01-31.json"), ("A", "relatorios/2027-01-31-2.json")]):
            problems, _ = portao.problems(changes)
            self.assertTrue(problems, changes)

    def test_quoted_or_odd_paths_are_refused(self):
        problems, _ = portao.problems([("A", '"tables/\\303\\251.json"'), ("A", "tables/../tools/x.json"),
                                       ("A", "relatorios/2027-01-31.json")])
        self.assertEqual(len(problems), 2)

    def test_symlinks_and_executables_are_refused(self):
        for mode in ("120000", "160000", "100755"):
            problems, _ = portao.problems([("A", "tables/x.json", mode), ("A", "relatorios/2027-01-31.json", "100644")])
            self.assertTrue(any("modo" in p for p in problems), mode)
        problems, _ = portao.problems([("A", "tables/x.json", "100644"), ("A", "relatorios/2027-01-31.json", "100644")])
        self.assertEqual(problems, [])

    def test_parse_raw_z(self):
        raw = ":000000 100644 0000 abcd A\0tables/x.json\0:100644 000000 abcd 0000 D\0tables/y.json\0"
        self.assertEqual(portao.parse_raw(raw), [("A", "tables/x.json", "100644"), ("D", "tables/y.json", "100644")])

    def test_report_name_must_be_a_date(self):
        for name in ("relatorios/x\nfoo=bar.json", "relatorios/$(id).json", "relatorios/2027-01-31.json\n",
                     "relatorios/r.json", "relatorios/2027-01-31-.json", "relatorios/2027-01-31-x.json"):
            problems, reports = portao.problems([("A", name)])
            self.assertTrue(problems, repr(name))
            self.assertEqual(reports, [], repr(name))
        problems, reports = portao.problems([("A", "relatorios/2027-01-31-2.json")])
        self.assertEqual((problems, reports), ([], ["relatorios/2027-01-31-2.json"]))

    def test_every_path_is_whitelisted(self):
        for name in ("tables/a\nb.json", "tables/$x.json", "tables/a b.json", "tables/a'b.json", "tables/\u00e9.json",
                     "tables/a\x00.json", "tables/a;b.json"):
            problems, _ = portao.problems([("A", name), ("A", "relatorios/2027-01-31.json")])
            self.assertTrue(any("suspeito" in p for p in problems), repr(name))

    def test_report_must_match_published_paths(self):
        tmp = Path(tempfile.mkdtemp()) / "r.json"
        tmp.write_text(json.dumps(REPORT))
        read = lambda path: tmp.read_text()  # noqa: E731
        self.assertEqual(portao.report_problems("r", {"tables/tru.2027-01-01.json"}, read), [])
        out = portao.report_problems("r", {"tables/outra.json"}, read)
        self.assertEqual(len(out), 1)
        self.assertIn("tables/tru.2027-01-01.json", out[0])
        for text in ("{nao", "[]", json.dumps({"issue": 1}), json.dumps({"publicado": [1]})):
            tmp.write_text(text)
            self.assertEqual(len(portao.report_problems("r", set(), read)), 1, text)
        self.assertEqual(len(portao.report_problems("r", set(), lambda p: open("/nao/existe/x").read())), 1)


def table_json(effective, published, sources, **extra):
    return json.dumps({"format": 2, "id": "a", "effective": effective, "published": published,
                       "sources": [{"title": f"F{i}", "url": f"https://diariodarepublica.pt/{i}", "consulted": published}
                                   for i in range(sources)], "values": {"k": 1}, **extra})


class PortaoGitTest(unittest.TestCase):
    def git(self, *args):
        return subprocess.run(["git", "-C", self.dir, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                              capture_output=True, text=True, check=True).stdout

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.git("init", "-q", "-b", "main")
        (Path(self.dir) / "tables").mkdir()
        (Path(self.dir) / "tables" / "a.json").write_text(table_json("2026-01-01", "2026-01-01", 1))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "claude/x")

    def run_gate(self, *extra):
        r = subprocess.run([sys.executable, str(Path(portao.__file__)), "--base", "main", *extra],
                           cwd=self.dir, capture_output=True, text=True)
        return r

    def test_cli_ok_writes_output(self):
        (Path(self.dir) / "relatorios").mkdir()
        (Path(self.dir) / "relatorios" / "2027-01-31.json").write_text(json.dumps(
            {**REPORT, "publicado": [{**REPORT["publicado"][0], "caminho": "tables/a.json", "vigencia": "2026-01-01"}]}))
        (Path(self.dir) / "tables" / "a.json").write_text(table_json("2026-01-01", "2026-10-11", 2))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "dados")
        out = Path(self.dir) / "out.txt"
        r = self.run_gate("--github-output", str(out))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(out.read_text(), "relatorio=relatorios/2027-01-31.json\n")

    def branch(self, files, published):
        """Um commit no ramo com ficheiros {caminho: texto} e um relatório que declara `published` [(caminho, vigencia)]."""
        for rel, text in files.items():
            (Path(self.dir) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(self.dir) / rel).write_text(text)
        (Path(self.dir) / "relatorios").mkdir(exist_ok=True)
        (Path(self.dir) / "relatorios" / "2027-01-31.json").write_text(json.dumps(
            {**REPORT, "publicado": [{**REPORT["publicado"][0], "caminho": c, "vigencia": v} for c, v in published]}))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "ramo")

    def assert_refused(self, *fragments):
        r = self.run_gate()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        for fragment in fragments:
            self.assertIn(fragment, r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_cli_refuses_changed_data_file_missing_from_publicado(self):
        self.branch({"tables/a.json": table_json("2026-01-01", "2026-10-11", 2),
                     "tables/b.json": table_json("2026-01-01", "2026-10-11", 1)}, [("tables/a.json", "2026-01-01")])
        self.assert_refused("tables/b.json: mudou mas não está em publicado")

    def test_cli_refuses_retification_without_newer_published(self):
        self.branch({"tables/a.json": table_json("2026-01-01", "2026-01-01", 2)}, [("tables/a.json", "2026-01-01")])
        self.assert_refused("tables/a.json: retificação sem published novo")

    def test_cli_refuses_retification_with_older_published(self):
        self.branch({"tables/a.json": table_json("2026-01-01", "2025-12-31", 2)}, [("tables/a.json", "2026-01-01")])
        self.assert_refused("sem published novo")

    def test_cli_refuses_retification_without_new_source(self):
        self.branch({"tables/a.json": table_json("2026-01-01", "2026-10-11", 1)}, [("tables/a.json", "2026-01-01")])
        self.assert_refused("tables/a.json: retificação sem fonte nova")

    def test_cli_refuses_vigencia_that_differs_from_effective(self):
        self.branch({"tables/a.json": table_json("2026-01-01", "2026-10-11", 2)}, [("tables/a.json", "2027-01-01")])
        self.assert_refused("vigência 2027-01-01 mas o ficheiro tem effective 2026-01-01")

    def test_cli_new_file_needs_no_retification_proof_but_a_matching_vigencia(self):
        self.branch({"tables/a.2027-01-01.json": table_json("2027-01-01", "2026-10-11", 1)}, [("tables/a.2027-01-01.json", "2027-01-01")])
        r = self.run_gate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_cli_unreadable_data_file_is_a_problem_not_a_traceback(self):
        self.branch({"tables/a.json": "{nao"}, [("tables/a.json", "2026-01-01")])
        self.assert_refused("tables/a.json: não consegui conferir")

    def test_cli_retification_with_missing_published_is_a_problem(self):
        self.branch({"tables/a.json": json.dumps({"effective": "2026-01-01", "sources": [1, 2, 3]})}, [("tables/a.json", "2026-01-01")])
        self.assert_refused("retificação sem «published» válido")

    def test_cli_refuses_symlink_and_tools(self):
        (Path(self.dir) / "relatorios").mkdir()
        (Path(self.dir) / "relatorios" / "2027-01-31.json").write_text("{}")
        os.symlink("../tools", Path(self.dir) / "tables" / "ln.json")
        (Path(self.dir) / "tools").mkdir()
        (Path(self.dir) / "tools" / "x.py").write_text("")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "mau")
        r = self.run_gate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("tools/x.py", r.stdout)
        self.assertIn("tables/ln.json", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_cli_refuses_report_that_lies_about_published(self):
        (Path(self.dir) / "relatorios").mkdir()
        (Path(self.dir) / "relatorios" / "2027-01-31.json").write_text(json.dumps(REPORT))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "r")
        r = self.run_gate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("tables/tru.2027-01-01.json", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_cli_refuses_malformed_report(self):
        (Path(self.dir) / "relatorios").mkdir()
        (Path(self.dir) / "relatorios" / "2027-01-31.json").write_text("{nao")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "r")
        r = self.run_gate()
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_cli_refuses_branch_behind_main(self):
        (Path(self.dir) / "relatorios").mkdir()
        (Path(self.dir) / "relatorios" / "2027-01-31.json").write_text("{}")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "r")
        self.git("checkout", "-q", "main")
        (Path(self.dir) / "tables" / "b.json").write_text("{}")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "main avança")
        self.git("checkout", "-q", "claude/x")
        r = self.run_gate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("não parte", r.stdout)

    def test_cli_unknown_base_is_a_clear_error(self):
        r = subprocess.run([sys.executable, str(Path(portao.__file__)), "--base", "origin/nao-existe"],
                           cwd=self.dir, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)
        self.assertTrue(r.stdout.strip())


class RelatorioTest(unittest.TestCase):
    def test_actions(self):
        acts = relatorio.actions(REPORT)
        self.assertEqual(acts[0]["titulo"], "Publicado: TRU 2027")
        self.assertTrue(acts[0]["fechar"])
        self.assertEqual(acts[0]["etiquetas"], ["publicado"])
        self.assertIn("2027-01-01", acts[0]["corpo"])
        self.assertEqual(acts[1]["titulo"], "Precisa de ti: Carreira de TSDT com níveis novos")
        self.assertFalse(acts[1]["fechar"])
        self.assertEqual(acts[2], {"tipo": "fechar", "numero": 12, "comentario": acts[2]["comentario"]})
        self.assertIn("Sem alterações: Despacho n.º 2/2027", acts[2]["comentario"])

    def test_nothing_published_still_closes_the_issue(self):
        rep = dict(REPORT, publicado=[], precisaDeTi=[])
        acts = relatorio.actions(rep)
        self.assertEqual([a["tipo"] for a in acts], ["fechar"])

    def test_check_rejects_bad_report(self):
        for bad in ({**REPORT, "issue": "12"}, {**REPORT, "publicado": [{"caminho": "careers/x.json", "titulo": "x", "vigencia": "2027-01-01", "fontes": []}]},
                    {k: v for k, v in REPORT.items() if k != "semAlteracoes"},
                    {**REPORT, "publicado": [{**REPORT["publicado"][0], "vigencia": "1/1/2027"}]}):
            with self.assertRaises(ValueError):
                relatorio.check(bad)

    def test_check_rejects_more_bad_reports(self):
        pub = REPORT["publicado"][0]
        for bad in ({**REPORT, "issue": True}, {**REPORT, "issue": 0}, [], {**REPORT, "publicado": ["x"]},
                    {**REPORT, "publicado": [{**pub, "caminho": "tables/../tools/x.py"}]},
                    {**REPORT, "publicado": [{**pub, "vigencia": "2027-01-01\n"}]},
                    {**REPORT, "precisaDeTi": [{"titulo": "x", "texto": "y"}]}):
            with self.assertRaises(ValueError):
                relatorio.check(bad)

    def test_cli_bad_inputs_give_clear_error(self):
        d = Path(tempfile.mkdtemp())
        (d / "mau.json").write_text("{nao é json")
        (d / "feio.json").write_text(json.dumps({"issue": "x"}))
        for name in ("mau.json", "feio.json", "nao-existe.json"):
            r = subprocess.run([sys.executable, str(Path(relatorio.__file__)), str(d / name), "--issues", str(d / "i.json")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, name)
            self.assertNotIn("Traceback", r.stderr)
            self.assertTrue(r.stdout.strip() or r.stderr.strip())
        self.assertFalse((d / "i.json").exists())

    def test_cli_writes_actions(self):
        d = Path(tempfile.mkdtemp())
        (d / "r.json").write_text(json.dumps(REPORT))
        relatorio.main([str(d / "r.json"), "--issues", str(d / "i.json")])
        self.assertEqual(json.loads((d / "i.json").read_text())[-1]["numero"], 12)

    def test_long_titles_are_capped(self):
        rep = {**REPORT, "precisaDeTi": [{"titulo": "x" * 400, "texto": "t", "fontes": []}],
               "publicado": [{**REPORT["publicado"][0], "titulo": "y" * 400}]}
        for a in relatorio.actions(rep):
            if a["tipo"] == "criar":
                self.assertLessEqual(len(a["titulo"]), 250)
                self.assertTrue(a["titulo"].endswith("…"))


class IssuesTest(unittest.TestCase):
    def test_run_creates_labels_issues_and_closes(self):
        calls = []

        def gh(args, stdin=None):
            calls.append((args, stdin))
            if args[:2] == ["issue", "view"]:
                return json.dumps({"state": "OPEN", "labels": [{"name": "novidade"}]})
            return "https://github.com/bessa8/scala-catalog/issues/77" if args[:2] == ["issue", "create"] else ""

        issues.run(relatorio.actions(REPORT), gh)
        self.assertEqual(calls[0][0], ["issue", "view", "12", "--json", "state,labels"])
        calls.pop(0)
        self.assertEqual(calls[0][0], ["label", "create", "precisa-de-ti", "--force"])
        self.assertEqual(calls[1][0], ["label", "create", "publicado", "--force"])
        self.assertEqual(calls[2][0][:4], ["issue", "create", "--title", "Publicado: TRU 2027"])
        self.assertEqual(calls[3][0], ["issue", "close", "77"])
        self.assertEqual(calls[-1][0][:3], ["issue", "close", "12"])

    def _gh_for(self, view, calls):
        def gh(args, stdin=None):
            calls.append(args)
            if args[:2] == ["issue", "create"]:
                return "https://github.com/bessa8/scala-catalog/issues/88"
            return view if args[:2] == ["issue", "view"] else ""
        return gh

    def test_close_only_open_issue_with_novidade_or_rever_and_before_any_mutation(self):
        acts = relatorio.actions(REPORT)
        for view in (json.dumps({"state": "CLOSED", "labels": [{"name": "novidade"}]}),
                     json.dumps({"state": "OPEN", "labels": [{"name": "precisa-de-ti"}]}),
                     json.dumps({"state": "OPEN", "labels": []}),
                     "nao é json", json.dumps([]), json.dumps({"state": "OPEN", "labels": "x"})):
            calls = []
            with self.assertRaises(ValueError):
                issues.run(acts, self._gh_for(view, calls))
            self.assertTrue(all(c[:2] == ["issue", "view"] for c in calls), (view, calls))
        for label in ("novidade", "rever"):
            calls = []
            issues.run(acts, self._gh_for(json.dumps({"state": "OPEN", "labels": [{"name": label}]}), calls))
            self.assertEqual(calls[-1][:3], ["issue", "close", "12"])

    def test_missing_file_does_nothing(self):
        issues.main([str(Path(tempfile.mkdtemp()) / "nao-existe.json")])

    def test_unknown_action_is_refused_before_calling_gh(self):
        calls = []
        with self.assertRaises(ValueError):
            issues.run([{"tipo": "criar", "titulo": "t", "corpo": "c", "etiquetas": []}, {"tipo": "apagar"}],
                       lambda a, stdin=None: calls.append(a) or "")
        self.assertEqual(calls, [])

    def test_gh_failure_is_a_clear_error(self):
        d = Path(tempfile.mkdtemp())
        (d / "a.json").write_text("{nao é json")
        r = subprocess.run([sys.executable, str(Path(issues.__file__)), str(d / "a.json")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)

    def test_run_returns_the_created_issues_with_number_and_labels(self):
        acts = [{"tipo": "criar", "titulo": "A", "corpo": "c", "etiquetas": ["novidade"]},
                {"tipo": "criar", "titulo": "B", "corpo": "c", "etiquetas": ["publicado"], "fechar": True}]
        urls = iter(["https://github.com/bessa8/scala-catalog/issues/41", "https://github.com/bessa8/scala-catalog/issues/42"])

        def gh(args, stdin=None):
            return next(urls) if args[:2] == ["issue", "create"] else ""

        self.assertEqual(issues.run(acts, gh), [{"numero": 41, "titulo": "A", "etiquetas": ["novidade"]},
                                                 {"numero": 42, "titulo": "B", "etiquetas": ["publicado"]}])
        self.assertEqual(issues.run([{"tipo": "fechar", "numero": 5, "comentario": "x"}],
                                    lambda a, stdin=None: json.dumps({"state": "OPEN", "labels": [{"name": "rever"}]})
                                    if a[:2] == ["issue", "view"] else ""), [])

    def test_criadas_option_writes_the_list_and_missing_input_writes_an_empty_one(self):
        d = Path(tempfile.mkdtemp())
        (d / "a.json").write_text(json.dumps([{"tipo": "criar", "titulo": "A", "corpo": "c", "etiquetas": ["novidade"]}]))
        fake = d / "bin"
        fake.mkdir()
        gh = fake / "gh"
        gh.write_text('#!/bin/sh\nif [ "$1 $2" = "issue create" ]; then echo https://github.com/bessa8/scala-catalog/issues/9; fi\n')
        gh.chmod(0o755)
        env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}")
        r = subprocess.run([sys.executable, str(Path(issues.__file__)), str(d / "a.json"), "--criadas", str(d / "c.json")],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((d / "c.json").read_text()), [{"numero": 9, "titulo": "A", "etiquetas": ["novidade"]}])
        issues.main([str(d / "nao-existe.json"), "--criadas", str(d / "vazia.json")])
        self.assertEqual(json.loads((d / "vazia.json").read_text()), [])

    def test_no_argument_does_nothing(self):
        issues.main([])


TOKEN = "segredo-do-token-123"
URL = "https://api.anthropic.com/v1/claude_code/routines/abc/fire"
OK = (200, {"type": "routine_fire", "claude_code_session_url": "https://claude.ai/code/session_1"})


class DispararTest(unittest.TestCase):
    def run_main(self, argv, env, responses=None):
        calls = []
        queue = list(responses or [OK])

        def post(url, headers, body):
            calls.append((url, headers, body))
            return queue.pop(0) if len(queue) > 1 else queue[0]

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = disparar.main(argv, env, post)
        return code, calls, out.getvalue()

    def criadas(self, items):
        p = Path(tempfile.mkdtemp()) / "criadas.json"
        p.write_text(json.dumps(items))
        return str(p)

    def test_not_configured_is_a_dry_run(self):
        for env in ({}, {"ROTINA_URL": URL}, {"ROTINA_TOKEN": TOKEN}, {"ROTINA_URL": "", "ROTINA_TOKEN": ""}):
            code, calls, out = self.run_main(["--issue", "7"], env)
            self.assertEqual((code, calls), (0, []))
            self.assertIn("Rotina não configurada (sem ROTINA_URL/ROTINA_TOKEN): nada disparado.", out)

    def test_fires_with_the_right_url_headers_and_body(self):
        code, calls, out = self.run_main(["--issue", "7"], {"ROTINA_URL": URL, "ROTINA_TOKEN": TOKEN})
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        url, headers, body = calls[0]
        self.assertEqual(url, URL)
        self.assertEqual(headers, {"Authorization": f"Bearer {TOKEN}",
                                   "anthropic-beta": "experimental-cc-routine-2026-04-01",
                                   "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
        self.assertEqual(json.loads(body), {"text": "Trata a issue #7 do repositório bessa8/scala-catalog. Segue o ROTINA.md."})
        self.assertNotIn(TOKEN, body.decode() if isinstance(body, bytes) else body)
        self.assertEqual([k for k, v in headers.items() if TOKEN in v], ["Authorization"])
        self.assertIn("https://claude.ai/code/session_1", out)
        self.assertNotIn(TOKEN, out)

    def test_http_error_or_wrong_response_exits_1_without_the_token(self):
        for resp in ((500, {"error": TOKEN}), (200, {"type": "outra-coisa"}), (200, "nao é json"), (200, ["x"]), (0, None)):
            code, calls, out = self.run_main(["--issue", "7"], {"ROTINA_URL": URL, "ROTINA_TOKEN": TOKEN}, [resp])
            self.assertEqual(code, 1, resp)
            self.assertNotIn(TOKEN, out)

    def test_post_that_raises_exits_1_without_the_token(self):
        def post(url, headers, body):
            raise OSError(f"falhou {TOKEN}")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = disparar.main(["--issue", "7"], {"ROTINA_URL": URL, "ROTINA_TOKEN": TOKEN}, post)
        self.assertEqual(code, 1)
        self.assertNotIn(TOKEN, out.getvalue())

    def test_criadas_fires_only_for_novidade(self):
        f = self.criadas([{"numero": 3, "titulo": "a", "etiquetas": ["novidade"]},
                          {"numero": 4, "titulo": "b", "etiquetas": ["publicado"]},
                          {"numero": 5, "titulo": "c", "etiquetas": ["precisa-de-ti"]},
                          {"numero": 6, "titulo": "d", "etiquetas": ["novidade", "x"]}])
        code, calls, _ = self.run_main(["--criadas", f], {"ROTINA_URL": URL, "ROTINA_TOKEN": TOKEN})
        self.assertEqual(code, 0)
        self.assertEqual([json.loads(c[2])["text"][:17] for c in calls], ["Trata a issue #3 ", "Trata a issue #6 "])

    def test_criadas_missing_or_empty_fires_nothing_and_a_failure_does_not_stop_the_others(self):
        env = {"ROTINA_URL": URL, "ROTINA_TOKEN": TOKEN}
        for argv in (["--criadas", str(Path(tempfile.mkdtemp()) / "nao-existe.json")], ["--criadas", self.criadas([])]):
            self.assertEqual(self.run_main(argv, env)[:2], (0, []))
        f = self.criadas([{"numero": 3, "titulo": "a", "etiquetas": ["novidade"]},
                          {"numero": 4, "titulo": "b", "etiquetas": ["novidade"]}])
        code, calls, _ = self.run_main(["--criadas", f], env, [(500, None), OK])
        self.assertEqual((code, len(calls)), (1, 2))

    def test_bad_url_is_refused_before_any_call(self):
        for url in ("http://api.anthropic.com/v1/x", "https://evil.example/v1/x", "https://api.anthropic.com.evil.example/x",
                    "https://api.anthropic.com@evil.example/x"):
            code, calls, out = self.run_main(["--issue", "7"], {"ROTINA_URL": url, "ROTINA_TOKEN": TOKEN})
            self.assertEqual((code, calls), (1, []), url)
            self.assertNotIn(TOKEN, out)

    def test_issue_must_be_a_positive_number(self):
        for bad in ("abc", "7; rm -rf", "-1", "0"):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                disparar.main(["--issue", bad], {"ROTINA_URL": URL, "ROTINA_TOKEN": TOKEN}, lambda *a: OK)

    def test_needs_exactly_one_of_issue_or_criadas(self):
        for argv in ([], ["--issue", "1", "--criadas", "x.json"]):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                disparar.main(argv, {}, lambda *a: OK)


if __name__ == "__main__":
    unittest.main()
