import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comparar  # noqa: E402
import plausivel  # noqa: E402


def table(tid, effective, values):
    return {"format": 2, "id": tid, "published": "2027-01-31", "effective": effective,
            "title": {"pt": "T", "en": "T"}, "unit": "monthly", "values": values, "sources": []}


class CompararTest(unittest.TestCase):
    def test_equal_ignoring_sources_published_title(self):
        a = table("tru", "2027-01-01", {"1": 100})
        b = dict(a, sources=[{"title": "x"}], published="2027-02-01", title="Outro")
        self.assertEqual(comparar.diff(a, b), [])

    def test_value_difference(self):
        a = table("tru", "2027-01-01", {"1": 100, "2": 200})
        b = table("tru", "2027-01-01", {"1": 100, "2": 201})
        self.assertEqual(comparar.diff(a, b), ["$.values.2: 200 ≠ 201"])

    def test_missing_key_and_list_length(self):
        a = {"tables": {"I": [{"upTo": 1}, {"upTo": None}]}}
        b = {"tables": {"I": [{"upTo": 1}], "II": []}}
        problems = comparar.diff(a, b)
        self.assertIn("$.tables.II: só na segunda", problems)
        self.assertIn("$.tables.I: 2 elementos contra 1", problems)

    def test_bool_is_not_int(self):
        self.assertEqual(comparar.diff({"x": 1}, {"x": True}), ["$.x: 1 ≠ true"])


class CompararDuplicadosTest(unittest.TestCase):
    def test_duplicate_keys_fail(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        (d / "a.json").write_text('{"values": {"1": 1, "1": 2}}', encoding="utf-8")
        (d / "b.json").write_text('{"values": {"1": 1}}', encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            comparar.main([str(d / "a.json"), str(d / "b.json")])
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("chave repetida: 1", out.getvalue())


class PlausivelTest(unittest.TestCase):
    def setUp(self):
        self.src = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.src)

    def put(self, rel, data):
        p = self.src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
        return rel

    def test_small_change_passes(self):
        self.put("tables/tru.2026-01-01.json", table("tru", "2026-01-01", {"1": 100000, "2": 110000}))
        new = self.put("tables/tru.2027-01-01.json", table("tru", "2027-01-01", {"1": 106000, "2": 113000}))
        self.assertEqual(plausivel.check(self.src, [new]), [])

    def test_big_change_and_missing_key(self):
        self.put("tables/medica.2026-01-01.json", table("medica", "2026-01-01", {"a": 100000, "b": 100000}))
        new = self.put("tables/medica.2027-01-01.json", table("medica", "2027-01-01", {"a": 120000}))
        problems = plausivel.check(self.src, [new])
        self.assertTrue(any("«a» muda 100000 → 120000" in p for p in problems), problems)
        self.assertTrue(any("«b» existia na versão anterior" in p for p in problems), problems)

    def test_tru_must_grow_by_level(self):
        new = self.put("tables/tru.2027-01-01.json", table("tru", "2027-01-01", {"1": 100000, "2": 99000, "10": 150000}))
        problems = plausivel.check(self.src, [new])
        self.assertTrue(any("nível 2" in p for p in problems), problems)

    def test_minimum_wage_never_drops(self):
        self.put("tables/smn.2026-01-01.json", table("smn", "2026-01-01", {"rmmg": 92000}))
        new = self.put("tables/smn.2027-01-01.json", table("smn", "2027-01-01", {"rmmg": 91000}))
        self.assertTrue(any("desce" in p for p in plausivel.check(self.src, [new])))

    def test_youth_ias_never_drops(self):
        self.put("tax/youth.2026-01-01.json", {"id": "youth", "effective": "2026-01-01", "percent": [100] * 10, "ias": 53713})
        new = self.put("tax/youth.2027-01-01.json", {"id": "youth", "effective": "2027-01-01", "percent": [100] * 10, "ias": 53000})
        self.assertTrue(any("IAS desce" in p for p in plausivel.check(self.src, [new])))

    def test_irs_same_tables(self):
        self.put("tax/irs-continente.2026-01-01.json", {"id": "irs-continente", "tables": {"I": [], "II": []}})
        new = self.put("tax/irs-continente.2027-01-01.json", {"id": "irs-continente", "tables": {"I": []}})
        self.assertTrue(any("tabelas" in p for p in plausivel.check(self.src, [new])))

    def test_contributions_change(self):
        self.put("tax/contributions.2025-01-01.json", {"id": "contributions", "ss": 1100, "cga": 1100, "health": 350})
        new = self.put("tax/contributions.2027-01-01.json", {"id": "contributions", "ss": 1100, "cga": 1100, "health": 500})
        self.assertTrue(any("health" in p for p in plausivel.check(self.src, [new])))

    def accept(self, rel):
        return {"caminho": rel, "sha256": plausivel.sha256(self.src, rel)}

    def test_accepted_with_matching_hash_is_skipped(self):
        self.put("tables/patrulha.2026-01-01.json", table("patrulha", "2026-01-01", {"x": 9003}))
        new = self.put("tables/patrulha.2027-01-01.json", table("patrulha", "2027-01-01", {"x": 11503}))
        self.assertNotEqual(plausivel.check(self.src, [new]), [])
        accepted = [self.accept(new)]
        self.assertEqual(plausivel.check(self.src, [new], accepted=accepted), [])
        # o ficheiro muda: a aceitação deixa de valer
        self.put(new, table("patrulha", "2027-01-01", {"x": 12000}))
        self.assertNotEqual(plausivel.check(self.src, [new], accepted=accepted), [])

    def test_hash_covers_data_not_metadata(self):
        base = table("patrulha", "2027-01-01", {"x": 11503})
        base["published"], base["sources"], base["title"] = "2026-10-01", [{"url": "a"}], "A"
        rel = self.put("tables/patrulha.2027-01-01.json", base)
        h = plausivel.sha256(self.src, rel)
        other = dict(base, published="2026-12-31", sources=[{"url": "b"}, {"url": "c"}], title="B")
        self.put(rel, other)
        self.assertEqual(plausivel.sha256(self.src, rel), h)
        self.put(rel, dict(other, values={"x": 11504}))
        self.assertNotEqual(plausivel.sha256(self.src, rel), h)

    def test_accepted_survives_metadata_change(self):
        self.put("tables/patrulha.2026-01-01.json", table("patrulha", "2026-01-01", {"x": 9003}))
        new = self.put("tables/patrulha.2027-01-01.json", table("patrulha", "2027-01-01", {"x": 11503}))
        accepted = [self.accept(new)]
        v = table("patrulha", "2027-01-01", {"x": 11503})
        v["published"], v["sources"] = "2027-02-02", [{"url": "https://diariodarepublica.pt/z"}]
        self.put(new, v)
        self.assertEqual(plausivel.check(self.src, [new], accepted=accepted), [])

    def test_hash_option_prints_hash(self):
        import io
        from contextlib import redirect_stdout
        new = self.put("tables/patrulha.2027-01-01.json", table("patrulha", "2027-01-01", {"x": 1}))
        buf = io.StringIO()
        with redirect_stdout(buf):
            plausivel.main(["--src", str(self.src), "--hash", new])
        self.assertEqual(buf.getvalue().strip(), plausivel.sha256(self.src, new))

    def test_old_accepted_format_is_rejected(self):
        with self.assertRaises(ValueError):
            plausivel.check(self.src, [], accepted=["tables/patrulha.2027-01-01.json"])

    def test_counts_only_checked_files(self):
        self.put("tables/a.2026-01-01.json", table("a", "2026-01-01", {"x": 1}))
        self.put("tables/b.2026-01-01.json", table("b", "2026-01-01", {"x": 1}))
        problems, checked, skipped = plausivel.check_counted(
            self.src, ["./tables/a.2026-01-01.json", "tables/b.2026-01-01.json"],
            accepted=[self.accept("tables/b.2026-01-01.json")])
        self.assertEqual((problems, checked, skipped), ([], 1, 1))

    def test_path_outside_pattern_is_a_problem(self):
        self.put("tables/README.md", {})
        problems = plausivel.check(self.src, ["tables/README.md", "x/tru.2027-01-01.json"])
        self.assertEqual(len(problems), 2)
        self.assertTrue(all("fora do padrão" in p for p in problems), problems)

    def test_leading_dot_slash_is_stripped(self):
        self.put("tables/tru.2026-01-01.json", table("tru", "2026-01-01", {"1": 100000}))
        new = self.put("tables/tru.2027-01-01.json", table("tru", "2027-01-01", {"1": 150000}))
        self.assertTrue(any("«1» muda" in p for p in plausivel.check(self.src, ["./" + new])))

    def test_errors_become_problems(self):
        self.put("tables/bad.2027-01-01.json", {"id": "bad"})  # sem «values»
        (self.src / "tables" / "junk.2027-01-01.json").write_text("{nao json", encoding="utf-8")
        problems = plausivel.check(self.src, ["tables/bad.2027-01-01.json", "tables/junk.2027-01-01.json",
                                              "tables/falta.2027-01-01.json"])
        self.assertEqual(len(problems), 3, problems)
        self.assertTrue(all("não foi possível conferir (" in p for p in problems), problems)

    def test_non_integer_values(self):
        new = self.put("tables/x.2027-01-01.json", table("x", "2027-01-01", {"a": True, "b": 1.5, "c": "9", "d": 3}))
        problems = plausivel.check(self.src, [new])
        self.assertEqual(len(problems), 3, problems)
        self.assertTrue(all("não é um inteiro" in p for p in problems), problems)

    def test_new_key_and_unit_change(self):
        self.put("tables/medica.2026-01-01.json", table("medica", "2026-01-01", {"a": 100000}))
        v = table("medica", "2027-01-01", {"a": 100000, "z": 100000})
        v["unit"] = "hourly"
        new = self.put("tables/medica.2027-01-01.json", v)
        problems = plausivel.check(self.src, [new])
        self.assertTrue(any("«z» é nova (a rotina não cria estrutura)" in p for p in problems), problems)
        self.assertTrue(any("«unit» muda monthly → hourly" in p for p in problems), problems)

    def test_youth_percent_change(self):
        self.put("tax/youth.2026-01-01.json", {"id": "youth", "percent": [100, 75], "ias": 53713})
        new = self.put("tax/youth.2027-01-01.json", {"id": "youth", "percent": [100, 50], "ias": 53713})
        self.assertTrue(any("«percent» muda" in p for p in plausivel.check(self.src, [new])))

    def test_irs_extras_change(self):
        self.put("tax/irs-madeira.2026-01-01.json", {"id": "irs-madeira", "tables": {"I": []}, "extras": {"a": 1}})
        new = self.put("tax/irs-madeira.2027-01-01.json", {"id": "irs-madeira", "tables": {"I": []}, "extras": {"a": 1, "b": 2}})
        self.assertTrue(any("extras" in p for p in plausivel.check(self.src, [new])))

    def test_unknown_tax_id(self):
        new = self.put("tax/novo.2027-01-01.json", {"id": "novo"})
        self.assertEqual(plausivel.check(self.src, [new]), [f"{new}: id de tabela fiscal desconhecido"])

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        "-c", "core.hooksPath=/dev/null", *args], cwd=self.src, check=True, capture_output=True)

    def test_retification_is_compared_with_its_old_content(self):
        self.git("init", "-q")
        rel = self.put("tables/medica.2027-01-01.json", table("medica", "2027-01-01", {"a": 100000, "b": 100000}))
        self.git("add", "."); self.git("commit", "-q", "-m", "base")
        # retificação: mesma versão, +50 %, chave nova e chave a menos
        self.put(rel, table("medica", "2027-01-01", {"a": 150000, "c": 1}))
        self.git("commit", "-q", "-am", "retifica")
        self.assertEqual(plausivel.check(self.src, [rel]), [])  # sem --desde não há com que comparar
        problems = plausivel.check(self.src, [rel], desde="HEAD~1")
        self.assertTrue(any("«a» muda 100000 → 150000" in p for p in problems), problems)
        self.assertTrue(any("«b» existia" in p for p in problems), problems)
        self.assertTrue(any("«c» é nova" in p for p in problems), problems)

    def test_desde_added_file_has_no_old_content(self):
        self.git("init", "-q")
        self.put("tables/x.2026-01-01.json", table("x", "2026-01-01", {"a": 1}))
        self.git("add", "."); self.git("commit", "-q", "-m", "base")
        new = self.put("tables/y.2027-01-01.json", table("y", "2027-01-01", {"a": 1}))
        self.git("add", "."); self.git("commit", "-q", "-m", "novo")
        self.assertEqual(plausivel.check(self.src, [new], desde="HEAD~1"), [])

    def test_bad_ref_is_a_problem_not_a_traceback(self):
        self.git("init", "-q")
        rel = self.put("tables/x.2026-01-01.json", table("x", "2026-01-01", {"a": 1}))
        problems = plausivel.check(self.src, [rel], desde="nao-existe")
        self.assertTrue(any("não foi possível conferir (RuntimeError" in p for p in problems), problems)

    def test_tru_may_gain_numeric_levels_but_nothing_else_may_be_new(self):
        self.put("tables/tru.2026-01-01.json", table("tru", "2026-01-01", {"43": 100000, "45": 110000}))
        ok = self.put("tables/tru.2027-01-01.json", table("tru", "2027-01-01", {"43": 100000, "44": 105000, "45": 110000, "51": 118000}))
        self.assertEqual(plausivel.check(self.src, [ok]), [])
        # a TRU não pode perder níveis, nem ter chaves que não sejam níveis, nem descer de nível para nível
        bad = self.put("tables/tru.2028-01-01.json", table("tru", "2028-01-01", {"43": 100000, "44": 99000, "x": 5, "-1": 5}))
        problems = plausivel.check(self.src, [bad])
        self.assertTrue(any("«45» existia" in p for p in problems), problems)
        self.assertTrue(any("«x» é nova" in p for p in problems), problems)
        self.assertTrue(any("«-1» é nova" in p for p in problems), problems)
        # outras tabelas continuam sem chaves novas, mesmo numéricas
        self.put("tables/medica.2026-01-01.json", table("medica", "2026-01-01", {"43": 100000}))
        other = self.put("tables/medica.2027-01-01.json", table("medica", "2027-01-01", {"43": 100000, "44": 100000}))
        self.assertTrue(any("«44» é nova" in p for p in plausivel.check(self.src, [other])))

    def test_sources_must_be_on_official_domains(self):
        def with_sources(*urls):
            t = table("x", "2027-01-01", {"a": 1})
            t["sources"] = [{"title": "T", "url": u, "consulted": "2027-01-31"} for u in urls]
            return t
        official = ("https://diariodarepublica.pt/dr/x", "https://files.diariodarepublica.pt/1s/a.pdf", "https://files.dre.pt/a.pdf",
                    "https://www.dgaep.gov.pt/x.pdf", "https://info.portaldasfinancas.gov.pt/x", "https://www2.adse.pt/x",
                    "https://www.acss.min-saude.pt/x", "https://joram.madeira.gov.pt/x", "https://www.cga.pt/x")
        self.assertEqual(plausivel.check(self.src, [self.put("tables/x.2027-01-01.json", with_sources(*official))]), [])
        bad = ("https://noticias.pt/x", "https://diariodarepublica.pt.evil.com/x", "https://evildiariodarepublica.pt/x",
               "https://diariodarepublica.pt@evil.com/x", "https://portaldasfinancas.gov.pt/x", "https://example.com/dgaep.gov.pt")
        problems = plausivel.check(self.src, [self.put("tables/y.2027-01-01.json", with_sources(*bad))])
        self.assertEqual(len([p for p in problems if "fonte fora dos domínios oficiais" in p]), len(bad), problems)
        # sem «url», ou «sources» que não é lista
        t = table("z", "2027-01-01", {"a": 1})
        t["sources"] = [{"title": "T"}]
        self.assertEqual(len(plausivel.check(self.src, [self.put("tables/z.2027-01-01.json", t)])), 1)
        t["sources"] = "x"
        self.assertEqual(len(plausivel.check(self.src, [self.put("tables/w.2027-01-01.json", t)])), 1)

    def test_sources_are_checked_even_for_accepted_files(self):
        t = table("patrulha", "2027-01-01", {"x": 11503})
        t["sources"] = [{"title": "T", "url": "https://noticias.pt/x", "consulted": "2027-01-31"}]
        new = self.put("tables/patrulha.2027-01-01.json", t)
        problems = plausivel.check(self.src, [new], accepted=[self.accept(new)])
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("fora dos domínios oficiais", problems[0])

    def test_every_catalog_file_passes_the_source_rule(self):
        root = Path(plausivel.ROOT)
        paths = sorted(str(p.relative_to(root)) for f in ("tables", "tax") for p in (root / f).glob("*.json"))
        bad = [p for p in plausivel.check(root, paths) if "fora dos domínios" in p]
        self.assertEqual(bad, [])

    def test_first_version_has_nothing_to_compare(self):
        new = self.put("tables/enfermagem.2026-01-01.json", table("enfermagem", "2026-01-01", {"enfermeiro-1": 165704}))
        self.assertEqual(plausivel.check(self.src, [new]), [])


if __name__ == "__main__":
    unittest.main()
