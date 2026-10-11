import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402


def minimal():
    return {
        "professions.json": {"format": 2, "published": "2026-10-07", "areas": [
            {"id": "saude", "title": {"pt": "Saúde", "en": "Health"}, "professions": [
                {"id": "enfermagem", "title": {"pt": "Enfermagem", "en": "Nursing"},
                 "search": "enfermeiro", "icon": "hospital", "career": "careers/enfermagem.json"}]}]},
        "institutions.json": {"format": 2, "published": "2026-10-07", "institutions": [
            {"id": "uls-sao-joao", "name": "ULS São João", "short": "ULS São João",
             "municipality": "Porto", "holiday": "06-24", "holidayName": "São João"}]},
        "templates/enf.json": {"format": 2, "id": "enf", "published": "2026-10-07",
                               "job": {"templates": [], "weeklyHours": 35}, "pay": {"calculationHours": 35}},
        "rules/ct-2026.json": {"format": 2, "id": "ct-2026", "published": "2026-10-07",
                               "title": {"pt": "Código do Trabalho", "en": "Labour Code"},
                               "rules": [{"name": "Noite", "dayType": "all"}]},
        "tables/tru.2026-01-01.json": {"format": 2, "id": "tru", "published": "2026-10-07",
                                       "effective": "2026-01-01", "title": {"pt": "TRU", "en": "TRU"},
                                       "unit": "monthly", "values": {"19": 165704}, "sources": []},
        "careers/enfermagem.json": {"format": 2, "id": "enfermagem", "published": "2026-10-07",
                                    "title": {"pt": "Enfermagem", "en": "Nursing"},
                                    "sectors": {"public": {
                                        "templates": "templates/enf.json", "rules": "rules/ct-2026.json",
                                        "institutions": True,
                                        "categories": [{"id": "enfermeiro", "title": {"pt": "Enfermeiro", "en": "Nurse"},
                                                        "regimes": [{"id": "35h", "title": {"pt": "35 h/semana", "en": "35 h/week"},
                                                                     "weeklyHours": 35, "pay": "monthly",
                                                                     "positions": [{"id": "1", "label": {"pt": "1.ª", "en": "1st"},
                                                                                    "table": "tru", "key": "19"}]}]}]}}},
    }


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.src = self.dir / "data"
        self.out = self.dir / "out"
        self.write(minimal())

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, files):
        for rel, data in files.items():
            path = self.src / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def edit(self, rel, change):
        path = self.src / rel
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def assertInvalid(self, fragment):
        with self.assertRaises(catalog.Invalid) as ctx:
            catalog.validate(self.src)
        self.assertIn(fragment, str(ctx.exception))

    def test_minimal_is_valid(self):
        catalog.validate(self.src)

    def test_position_must_point_to_existing_key(self):
        def change(d):
            d["sectors"]["public"]["categories"][0]["regimes"][0]["positions"][0]["key"] = "99"
        self.edit("careers/enfermagem.json", change)
        self.assertInvalid("chave «99»")

    def test_table_name_must_match_effective(self):
        self.edit("tables/tru.2026-01-01.json", lambda d: d.update(effective="2027-01-01"))
        self.assertInvalid("«effective» tem de ser 2026-01-01")

    def test_text_needs_both_languages(self):
        self.edit("careers/enfermagem.json", lambda d: d.update(title={"pt": "Enfermagem"}))
        self.assertInvalid("«pt» e «en»")

    def test_format_must_be_two(self):
        self.edit("rules/ct-2026.json", lambda d: d.update(format=3))
        self.assertInvalid("«format» tem de ser 2")

    def test_missing_career_file(self):
        (self.src / "careers/enfermagem.json").unlink()
        self.assertInvalid("careers/enfermagem.json")

    def test_holiday_rule(self):
        self.edit("institutions.json", lambda d: d["institutions"][0].update(holiday="24 junho"))
        self.assertInvalid("«holiday»")

    def test_institution_sources_are_checked(self):
        self.edit("institutions.json", lambda d: d.update(sources=[{"title": "Câmara", "url": "http://x.pt", "consulted": "2026-10-10"}]))
        self.assertInvalid("institutions.json: fonte 1")

    def test_institution_ids_are_unique(self):
        self.edit("institutions.json", lambda d: d["institutions"].append(dict(d["institutions"][0])))
        self.assertInvalid("ids repetidos")

    def test_institution_entries_must_be_objects(self):
        self.edit("institutions.json", lambda d: d["institutions"].append("uls-x"))
        self.assertInvalid("institutions.json: cada instituição tem de ser um objeto")

    def test_build_writes_files_and_manifest(self):
        catalog.build(self.src, self.out)
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], 2)
        paths = [f["path"] for f in manifest["files"]]
        self.assertIn("careers/enfermagem.json", paths)
        self.assertIn("tables/tru.2026-01-01.json", paths)
        entry = next(f for f in manifest["files"] if f["path"] == "careers/enfermagem.json")
        data = (self.out / "careers/enfermagem.json").read_bytes()
        self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(entry["bytes"], len(data))
        self.assertEqual(entry["published"], "2026-10-07")

    def test_build_keeps_unrelated_files(self):
        self.out.mkdir()
        (self.out / "enf.2026-10-07.sqlite").write_bytes(b"old")
        catalog.build(self.src, self.out)
        self.assertTrue((self.out / "enf.2026-10-07.sqlite").exists())

    def test_rotation_codes_must_be_templates_or_off_days(self):
        def change(d):
            d["sectors"]["public"]["rotations"] = [
                {"id": "x", "title": {"pt": "X", "en": "X"}, "codes": ["Q", "F"]}]
        self.edit("careers/enfermagem.json", change)
        self.assertInvalid("código «Q»")

    def test_rotation_with_template_ids_is_valid(self):
        self.edit("templates/enf.json", lambda d: d["job"].update(templates=[{"id": "M", "name": "Manhã", "category": "M", "start": 480, "end": 900}]))
        def change(d):
            d["sectors"]["public"]["rotations"] = [
                {"id": "x", "title": {"pt": "X", "en": "X"}, "codes": ["M", "F", "D"]}]
        self.edit("careers/enfermagem.json", change)
        catalog.validate(self.src)


    def test_bool_is_not_an_int(self):
        self.edit("tables/tru.2026-01-01.json", lambda d: d["values"].update({"19": True}))
        self.assertInvalid("inteiro positivo")

    def test_template_pay_types(self):
        self.edit("templates/enf.json", lambda d: d["pay"].update(supplementDelay=1.5))
        self.assertInvalid("«supplementDelay»")

    def test_holiday_must_be_a_real_date(self):
        self.edit("institutions.json", lambda d: d["institutions"][0].update(holiday="13-45"))
        self.assertInvalid("«holiday»")

    def test_career_path_prefix(self):
        self.edit("professions.json", lambda d: d["areas"][0]["professions"][0].update(career="tables/tru.2026-01-01.json"))
        self.assertInvalid("careers/")

    def test_hourly_regime_needs_calculation_hours(self):
        def change(d):
            r = d["sectors"]["public"]["categories"][0]["regimes"][0]
            r.update(pay="hourly", weeklyHours=0)
        self.edit("careers/enfermagem.json", change)
        self.assertInvalid("«calculationHours»")

    def test_rotation_codes_checked_against_regime_templates(self):
        self.edit("templates/enf.json", lambda d: d["job"].update(templates=[{"id": "M", "name": "Manhã", "category": "M", "start": 480, "end": 900}]))
        self.write({"templates/extra.json": {"format": 2, "id": "extra", "published": "2026-10-07", "job": {"templates": [{"id": "N", "name": "Noite", "category": "N", "start": 1260, "end": 510}]}, "pay": {}}})
        def change(d):
            s = d["sectors"]["public"]
            s["categories"][0]["regimes"][0]["templates"] = "templates/extra.json"
            s["rotations"] = [{"id": "x", "title": {"pt": "X", "en": "X"}, "codes": ["M", "F"]}]
        self.edit("careers/enfermagem.json", change)
        self.assertInvalid("código «M»")

    def test_verify_accepts_build_output_and_rejects_tampering(self):
        catalog.build(self.src, self.out)
        catalog.verify(self.out)
        path = self.out / "careers/enfermagem.json"
        path.write_text(path.read_text(encoding="utf-8").replace("Enfermagem", "Enfermagen"), encoding="utf-8")
        with self.assertRaises(catalog.Invalid) as ctx:
            catalog.verify(self.out)
        self.assertIn("sha256", str(ctx.exception))

    def test_verify_rejects_unlisted_file(self):
        catalog.build(self.src, self.out)
        (self.out / "tables").mkdir(exist_ok=True)
        extra = {"format": 2, "id": "x", "published": "2026-10-07", "effective": "2027-01-01", "title": {"pt": "X", "en": "X"}, "unit": "monthly", "values": {"1": 100}, "sources": []}
        (self.out / "tables/x.2027-01-01.json").write_text(json.dumps(extra), encoding="utf-8")
        with self.assertRaises(catalog.Invalid) as ctx:
            catalog.verify(self.out)
        self.assertIn("não está no manifest", str(ctx.exception))

    def test_build_in_place_writes_only_the_manifest(self):
        extra = self.src / "tools" / "estado.json"
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text('{"nao": "e catalogo"}', encoding="utf-8")
        report = self.src / "relatorios" / "2026-10-12.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("{}", encoding="utf-8")
        before = {p: p.read_bytes() for p in self.src.rglob("*.json")}
        manifest = catalog.build(self.src, self.src)
        paths = [e["path"] for e in manifest["files"]]
        self.assertIn("tables/tru.2026-01-01.json", paths)
        self.assertNotIn("tools/estado.json", paths)
        self.assertNotIn("relatorios/2026-10-12.json", paths)
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data, path)
        self.assertTrue((self.src / "manifest.json").exists())

    def test_files_outside_catalog_folders_are_ignored(self):
        stray = self.src / "tools" / "outro.json"
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_text("[]", encoding="utf-8")
        files = catalog.validate(self.src)
        self.assertNotIn("tools/outro.json", files)

    def good_source(self):
        return {"title": "Portaria n.º 1/2026", "url": "https://diariodarepublica.pt/x", "consulted": "2026-10-09"}

    def test_sources_are_optional(self):
        self.edit("tables/tru.2026-01-01.json", lambda d: d.pop("sources"))
        catalog.validate(self.src)

    def test_table_and_career_accept_valid_sources(self):
        self.edit("tables/tru.2026-01-01.json", lambda d: d.update(sources=[self.good_source()]))
        self.edit("careers/enfermagem.json", lambda d: d.update(sources=[self.good_source()]))
        catalog.validate(self.src)

    def test_source_needs_https_url(self):
        for url in (None, "http://dre.pt/x", "dre.pt"):
            bad = self.good_source()
            if url is None:
                del bad["url"]
            else:
                bad["url"] = url
            self.edit("tables/tru.2026-01-01.json", lambda d: d.update(sources=[bad]))
            self.assertInvalid("tables/tru.2026-01-01.json")
            self.assertInvalid("«url»")

    def test_source_needs_title_and_real_consulted_date(self):
        for key, value in (("title", " "), ("consulted", "9/10/2026"), ("consulted", "2026-13-45")):
            bad = self.good_source()
            bad[key] = value
            self.edit("careers/enfermagem.json", lambda d: d.update(sources=[bad]))
            self.assertInvalid("careers/enfermagem.json")
            self.assertInvalid(f"«{key}»")

    def test_sources_must_be_a_list_of_objects(self):
        self.edit("careers/enfermagem.json", lambda d: d.update(sources=["https://dre.pt"]))
        self.assertInvalid("careers/enfermagem.json")

    def test_build_does_not_copy_por_confirmar(self):
        (self.src / "por-confirmar.md").write_text("# Por confirmar\n", encoding="utf-8")
        manifest = catalog.build(self.src, self.out)
        self.assertFalse((self.out / "por-confirmar.md").exists())
        self.assertNotIn("por-confirmar.md", [f["path"] for f in manifest["files"]])

    def test_report_lists_tables_careers_and_pending(self):
        self.edit("tables/tru.2026-01-01.json", lambda d: d.update(sources=[self.good_source()]))
        report = catalog.report(self.src)
        self.assertIn("TRU", report)
        self.assertIn("1 657,04 €", report)
        self.assertIn("https://diariodarepublica.pt/x", report)
        self.assertIn("Enfermagem", report)
        self.assertIn("1.ª — tabela `tru`, chave `19`: 1 657,04 €", report)
        self.assertIn("## Por confirmar", report)
        self.assertIn("Nada por confirmar.", report)

    def test_report_includes_por_confirmar_file(self):
        (self.src / "por-confirmar.md").write_text("### Task 2\n- valor X por confirmar\n", encoding="utf-8")
        report = catalog.report(self.src)
        self.assertIn("valor X por confirmar", report)
        self.assertNotIn("Nada por confirmar.", report)

    def test_report_formats_hourly_values_and_lists_regimes_without_table(self):
        self.write({"tables/h.2026-01-01.json": {"format": 2, "id": "h", "published": "2026-10-07",
                                                 "effective": "2026-01-01", "title": {"pt": "Hora", "en": "Hour"},
                                                 "unit": "hourly", "values": {"a": 123456000}}})
        self.edit("careers/enfermagem.json", lambda d: d["sectors"]["public"]["categories"][0]["regimes"].append(
            {"id": "livre", "title": {"pt": "Livre", "en": "Free"}, "weeklyHours": 40.0, "pay": "monthly"}))
        report = catalog.report(self.src)
        self.assertIn("12,3456 €/h", report)
        self.assertIn("40 h/semana", report)
        self.assertNotIn("40.0", report)
        self.assertEqual(catalog.euros_per_hour(123456789), "12,3456789 €/h")
        self.assertEqual(catalog.euros_per_hour(120000000), "12,00 €/h")
        self.assertEqual(catalog.euros_per_hour(125000000), "12,50 €/h")
        self.assertIn("## Sem tabela", report)
        self.assertIn("Livre", report.split("## Sem tabela")[1])

    def test_report_names_pay_modes_in_portuguese(self):
        def add(rid, pay):
            self.edit("careers/enfermagem.json", lambda d: d["sectors"]["public"]["categories"][0]["regimes"].append(
                {"id": rid, "title": {"pt": rid, "en": rid}, "weeklyHours": 40.0, "pay": pay}))
        add("m", "monthly")
        add("h", "hourly")
        add("x", "hourlyFromMonthly")
        report = catalog.report(self.src)
        self.assertIn("40 h/semana, salário mensal)", report)
        self.assertIn("40 h/semana, à hora)", report)
        self.assertIn("40 h/semana, à hora, tirado do mensal (só extra))", report)
        self.assertNotIn("pagamento", report)
        self.assertNotIn("hourlyFromMonthly", report)

    def test_report_describes_questions_and_rotations(self):
        self.edit("templates/enf.json", lambda d: d["job"].update(templates=[{"id": "M", "name": "Manhã", "category": "M", "start": 480, "end": 900}]))
        def change(d):
            s = d["sectors"]["public"]
            s["rotations"] = [{"id": "x", "title": {"pt": "Rotação X", "en": "X"}, "codes": ["M", "F", "D"]}]
            s["questions"] = [{"id": "q", "label": {"pt": "Noites", "en": "Nights"},
                               "effect": {"monthlySupplement": {"perUnitCents": 250}}}]
        self.edit("careers/enfermagem.json", change)
        report = catalog.report(self.src)
        self.assertIn("Rotação X", report)
        self.assertIn("M F D", report)
        self.assertIn("Noites", report)
        self.assertIn("2,50 €", report)

    def test_report_writes_file_with_out(self):
        target = self.dir / "VERIFICAR.md"
        target.write_text(catalog.report(self.src), encoding="utf-8")
        self.assertTrue(target.read_text(encoding="utf-8").startswith("# "))


    def irs(self, **change):
        d = {"format": 2, "id": "irs-continente", "published": "2026-10-11", "effective": "2026-01-01",
             "title": {"pt": "Retenção na fonte (Continente)", "en": "Withholding tax (mainland)"},
             "tables": {t: [
                 {"upTo": 92000, "rate": 0, "deduction": 0, "perDependent": 0, "effectiveAtLimit": 0},
                 {"upTo": 104200, "rate": 1250, "deductionFormula": {"factor": 2.6, "limit": 127385},
                  "perDependent": 2143, "effectiveAtLimit": 53},
                 {"upTo": 181900, "rate": 2410, "deduction": 19333, "perDependent": 2143, "effectiveAtLimit": 135},
                 {"upTo": None, "rate": 4717, "deduction": 127231, "perDependent": 2143}]
                 for t in ("I", "II", "III", "IV", "V", "VI", "VII")},
             "extras": {"disabledDependent": {"single": 8482, "married1": 8482, "married2": 4241},
                        "spouseDisabled": 13571, "threePlusCut": 100, "overtimeShare": 50},
             "sources": [{"title": "Despacho n.º 233-A/2026", "url": "https://diariodarepublica.pt/x",
                          "consulted": "2026-10-11"}]}
        d.update(change)
        self.write({"tax/irs-continente.2026-01-01.json": d})

    def test_tax_irs_is_valid(self):
        self.irs()
        catalog.validate(self.src)

    def test_tax_needs_sources(self):
        self.irs(sources=[])
        self.assertInvalid("fonte oficial")

    def test_tax_lines_must_grow(self):
        self.irs()
        self.edit("tax/irs-continente.2026-01-01.json",
                  lambda d: d["tables"]["I"].__setitem__(2, {**d["tables"]["I"][2], "upTo": 100000}))
        self.assertInvalid("ordem crescente")

    def test_tax_last_line_has_no_limit(self):
        self.irs()
        self.edit("tax/irs-continente.2026-01-01.json",
                  lambda d: d["tables"]["I"][-1].__setitem__("upTo", 9999999))
        self.assertInvalid("última linha")

    def test_tax_all_tables(self):
        self.irs()
        self.edit("tax/irs-continente.2026-01-01.json", lambda d: d["tables"].pop("VII"))
        self.assertInvalid("VII")

    def test_tax_effective_rate_is_checked(self):
        self.irs()
        self.edit("tax/irs-continente.2026-01-01.json",
                  lambda d: d["tables"]["I"][2].__setitem__("effectiveAtLimit", 140))
        self.assertInvalid("taxa efetiva")

    def test_tax_unknown_id(self):
        self.write({"tax/irs-algarve.2026-01-01.json": {"format": 2, "id": "irs-algarve", "published": "2026-10-11",
                                                        "effective": "2026-01-01"}})
        self.assertInvalid("irs-algarve")

    def test_tax_contributions_and_youth(self):
        src = [{"title": "Lei", "url": "https://diariodarepublica.pt/y", "consulted": "2026-10-11"}]
        self.write({
            "tax/contributions.2025-01-01.json": {"format": 2, "id": "contributions", "published": "2026-10-11",
                                                  "effective": "2025-01-01", "title": {"pt": "Contribuições", "en": "Contributions"},
                                                  "ss": 1100, "cga": 1100, "health": 350, "sources": src},
            "tax/youth.2026-01-01.json": {"format": 2, "id": "youth", "published": "2026-10-11",
                                          "effective": "2026-01-01", "title": {"pt": "IRS Jovem", "en": "Youth IRS"},
                                          "percent": [100, 75, 75, 75, 50, 50, 50, 25, 25, 25], "ias": 53713,
                                          "sources": src},
        })
        catalog.validate(self.src)
        self.edit("tax/youth.2026-01-01.json", lambda d: d.__setitem__("percent", [100, 75]))
        self.assertInvalid("10 anos")

    def test_tax_is_built(self):
        self.irs()
        catalog.build(self.src, self.out)
        self.assertTrue((self.out / "tax" / "irs-continente.2026-01-01.json").exists())

    def test_report_lists_tax_tables_with_every_line(self):
        self.irs()
        src = [{"title": "Lei n.º 110/2009", "url": "https://diariodarepublica.pt/y", "consulted": "2026-10-11"}]
        self.write({
            "tax/contributions.2025-01-01.json": {"format": 2, "id": "contributions", "published": "2026-10-11",
                                                  "effective": "2025-01-01", "title": {"pt": "Contribuições", "en": "Contributions"},
                                                  "ss": 1100, "cga": 1100, "health": 350, "sources": src},
            "tax/youth.2026-01-01.json": {"format": 2, "id": "youth", "published": "2026-10-11",
                                          "effective": "2026-01-01", "title": {"pt": "IRS Jovem", "en": "Youth IRS"},
                                          "percent": [100, 75, 75, 75, 50, 50, 50, 25, 25, 25], "ias": 53713,
                                          "sources": src},
        })
        report = catalog.report(self.src)
        self.assertIn("## Tabelas fiscais", report)
        for expected in (
            "`irs-continente`", "vigência 2026-01-01", "#### Tabela I", "#### Tabela VII",
            "até 920,00 €", "taxa 12,50 %", "parcela a abater taxa × 2,6 × (1 273,85 € − R)", "parcela a abater 193,33 €",
            "por dependente 21,43 €", "taxa efetiva no limite 5,3 %", "acima de 1 819,00 €", "taxa 47,17 %",
            "Despacho n.º 233-A/2026", "https://diariodarepublica.pt/x",
            "dependente com deficiência: 84,82 € (solteiro)", "42,41 € (casado, dois titulares)",
            "cônjuge com deficiência: 135,71 €", "retirar 1,00 pp", "50 % da taxa efetiva",
            "`contributions`", "Segurança Social 11,00 %", "CGA 11,00 %", "saúde 3,50 %", "Lei n.º 110/2009",
            "`youth`", "100 %, 75 %, 75 %, 75 %, 50 %, 50 %, 50 %, 25 %, 25 %, 25 %", "IAS 537,13 €",
        ):
            self.assertIn(expected, report)
        self.assertEqual(report.count("#### Tabela"), 7)
        # A secção vem antes de «Sem tabela» e de «Por confirmar».
        self.assertLess(report.index("## Tabelas fiscais"), report.index("## Sem tabela"))

    def test_report_without_tax_files_has_no_tax_section(self):
        self.assertNotIn("## Tabelas fiscais", catalog.report(self.src))

    def test_sector_deductions(self):
        self.edit("careers/enfermagem.json",
                  lambda d: d["sectors"]["public"].__setitem__("deductions", {"social": "cga", "health": True}))
        catalog.validate(self.src)
        self.edit("careers/enfermagem.json",
                  lambda d: d["sectors"]["public"].__setitem__("deductions", {"social": "adse"}))
        self.assertInvalid("deductions")


if __name__ == "__main__":
    unittest.main()
