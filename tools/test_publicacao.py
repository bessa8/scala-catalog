import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
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


class PortaoGitTest(unittest.TestCase):
    def git(self, *args):
        return subprocess.run(["git", "-C", self.dir, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                              capture_output=True, text=True, check=True).stdout

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.git("init", "-q", "-b", "main")
        (Path(self.dir) / "tables").mkdir()
        (Path(self.dir) / "tables" / "a.json").write_text("{}")
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
            {**REPORT, "publicado": [{**REPORT["publicado"][0], "caminho": "tables/a.json"}]}))
        (Path(self.dir) / "tables" / "a.json").write_text('{"x":1}')
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "dados")
        out = Path(self.dir) / "out.txt"
        r = self.run_gate("--github-output", str(out))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(out.read_text(), "relatorio=relatorios/2027-01-31.json\n")

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

    def test_no_argument_does_nothing(self):
        issues.main([])


if __name__ == "__main__":
    unittest.main()
