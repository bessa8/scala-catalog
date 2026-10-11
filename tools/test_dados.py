import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


class TabelasPorPosicaoTest(unittest.TestCase):
    def test_same_euros_as_tru_2026(self):
        tru = load("tables/tru.2026-01-01.json")["values"]
        levels = {
            "enfermagem": {"enfermeiro": [19, 23, 27, 31, 34, 37, 40, 43, 46, 49, 52],
                           "especialista": [24, 28, 31, 34, 37, 40, 43, 46, 49, 52],
                           "gestor": [38, 42, 46, 50, 53, 56, 58]},
            "farmaceutico": {"assistente": [27, 29, 31, 33, 35, 37, 39],
                             "assessor": [38, 41, 43, 45, 47, 49],
                             "assessor-senior": [47, 49, 54, 59, 64]},
        }
        for career, cats in levels.items():
            table = load(f"tables/{career}.2026-01-01.json")
            self.assertEqual(table["effective"], "2026-01-01")
            expected = {f"{cat}-{i}": tru[str(level)] for cat, ls in cats.items() for i, level in enumerate(ls, 1)}
            self.assertEqual(table["values"], expected, career)
            for sector in load(f"careers/{career}.json")["sectors"].values():
                for cat in sector["categories"]:
                    for reg in cat["regimes"]:
                        for p in reg["positions"]:
                            self.assertEqual(p["table"], career)
                            self.assertEqual(p["key"], f"{cat['id']}-{p['id']}")
                            self.assertNotIn("nível", p["label"]["pt"])
                            self.assertNotIn("level", p["label"]["en"])


class FontesDasTabelasTest(unittest.TestCase):
    def test_no_table_lists_the_same_source_url_twice(self):
        for path in sorted(list((ROOT / "tables").glob("*.json")) + list((ROOT / "tax").glob("*.json"))):
            urls = [s["url"] for s in json.loads(path.read_text(encoding="utf-8")).get("sources", [])]
            self.assertEqual(len(urls), len(set(urls)), path.name)

    def test_position_tables_do_not_cite_the_35_hour_law_as_a_value_source(self):
        for career in ("enfermagem", "farmaceutico"):
            titles = [s["title"] for s in load(f"tables/{career}.2026-01-01.json")["sources"]]
            self.assertFalse([t for t in titles if "18/2016" in t], career)


if __name__ == "__main__":
    unittest.main()
