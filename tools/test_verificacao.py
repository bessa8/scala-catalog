import json
import shutil
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

    def test_accepted_paths_are_skipped(self):
        self.put("tables/patrulha.2026-01-01.json", table("patrulha", "2026-01-01", {"x": 9003}))
        new = self.put("tables/patrulha.2027-01-01.json", table("patrulha", "2027-01-01", {"x": 11503}))
        self.assertNotEqual(plausivel.check(self.src, [new]), [])
        self.assertEqual(plausivel.check(self.src, [new], accepted=[new]), [])

    def test_first_version_has_nothing_to_compare(self):
        new = self.put("tables/enfermagem.2026-01-01.json", table("enfermagem", "2026-01-01", {"enfermeiro-1": 165704}))
        self.assertEqual(plausivel.check(self.src, [new]), [])


if __name__ == "__main__":
    unittest.main()
