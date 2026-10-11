import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vigia  # noqa: E402

RSS = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0"><channel><title>Diário do Dia - Série II</title>
<item><title>Despacho n.º 1-A/2027  -  Diário da República n.º 3/2027, Série II de 2027-01-05</title>
<description type="html"><![CDATA[Finanças - Gabinete da Secretária de Estado dos Assuntos Fiscais Aprova as tabelas de retenção na fonte para vigorarem durante o ano de 2027.]]></description>
<link><![CDATA[https://diariodarepublica.pt/dr/detalhe/despacho/1-a-2027-1]]></link></item>
<item><title>Despacho n.º 2/2027</title>
<description type="html"><![CDATA[Provedoria de Justiça Subdelegação de competências.]]></description>
<link><![CDATA[https://diariodarepublica.pt/dr/detalhe/despacho/2-2027-2]]></link></item>
</channel></rss>"""

CONFIG = {
    "fontes": {
        "dr2": {"tipo": "rss", "url": "https://dr/serie2.xml"},
        "srap": {"tipo": "links", "url": "https://dgaep/srap", "padrao": "SRAP[^\"'/]*\\.pdf", "tema": "tru"},
        "at": {"tipo": "circulares", "url": "https://at/Documents/",
               "nomes": ["Circular_{n}_{ano}.pdf", "Circular_{n}_{ano}_RAM.pdf"], "tema": "irs"},
    },
    "temas": [
        {"id": "irs", "tabelas": ["tax/irs-*"], "palavras": ["retenção na fonte"]},
        {"id": "tru", "tabelas": ["tables/tru"], "palavras": ["tabela remuneratoria unica"]},
    ],
}

NOW = datetime.datetime(2027, 1, 5, 6, 0, tzinfo=datetime.timezone.utc)


def pages(srap=('SRAP_2026.pdf',), circulars=()):
    html = "".join(f'<a href="https://www.dgaep.gov.pt/upload//catalogo/{n}">x</a>' for n in srap)
    def fetch(url):
        if url == "https://dr/serie2.xml":
            return RSS
        if url == "https://dgaep/srap":
            return html
        raise OSError("sem rede")
    def exists(url):
        return url.rsplit("/", 1)[-1] in circulars
    return fetch, exists


class VigiaTest(unittest.TestCase):
    def test_normalize_drops_accents_case_and_spaces(self):
        self.assertEqual(vigia.normalize("  Retenção  na FONTE "), "retencao na fonte")

    def test_rss_items(self):
        items = vigia.rss_items(RSS)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["link"], "https://diariodarepublica.pt/dr/detalhe/despacho/1-a-2027-1")
        self.assertIn("tabelas de retenção", items[0]["resumo"])

    def test_rss_that_is_an_html_page_fails(self):
        with self.assertRaises(ValueError):
            vigia.rss_items("<html><body>Erro</body></html>")

    def test_daily_finds_rss_lead_once(self):
        fetch, exists = pages()
        state, issues = vigia.daily(vigia.empty_state(), CONFIG, fetch, exists, NOW)
        leads = [p for p in state["pistas"] if p["fonte"] == "dr2"]
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["temas"], ["irs"])
        self.assertEqual(leads[0]["vistaEm"], "2027-01-05")
        state, _ = vigia.daily(state, CONFIG, fetch, exists, NOW + datetime.timedelta(days=1))
        self.assertEqual(len([p for p in state["pistas"] if p["fonte"] == "dr2"]), 1)
        self.assertEqual(issues, [])

    def test_first_run_of_links_and_circulars_only_records(self):
        fetch, exists = pages(circulars=("Circular_1_2027.pdf",))
        state, _ = vigia.daily(vigia.empty_state(), CONFIG, fetch, exists, NOW)
        self.assertEqual([p for p in state["pistas"] if p["fonte"] != "dr2"], [])
        self.assertEqual(state["fontes"]["srap"]["lista"], ["SRAP_2026.pdf"])
        self.assertEqual(state["fontes"]["at"]["ultimas"]["2027"], 1)

    def test_new_srap_and_circular_become_leads(self):
        fetch, exists = pages(circulars=("Circular_1_2027.pdf",))
        state, _ = vigia.daily(vigia.empty_state(), CONFIG, fetch, exists, NOW)
        fetch, exists = pages(srap=("SRAP_2026.pdf", "SRAP_2027.pdf"),
                              circulars=("Circular_1_2027.pdf", "Circular_3_2027_RAM.pdf"))
        state, _ = vigia.daily(state, CONFIG, fetch, exists, NOW + datetime.timedelta(days=1))
        titles = [p["titulo"] for p in state["pistas"] if p["fonte"] != "dr2"]
        self.assertIn("Documento novo: SRAP_2027.pdf", titles)
        self.assertIn("Circular n.º 3/2027 da AT", titles)
        self.assertEqual(state["fontes"]["at"]["ultimas"]["2027"], 3)

    def test_source_failing_three_days_opens_one_issue(self):
        config = {"fontes": {"dr1": {"tipo": "rss", "url": "https://dr/off.xml"}}, "temas": CONFIG["temas"]}
        fetch, exists = pages()
        state, issues = vigia.empty_state(), []
        for day in range(4):
            state, new = vigia.daily(state, config, fetch, exists, NOW + datetime.timedelta(days=day))
            issues += new
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["titulo"], "Fonte inacessível: dr1")
        self.assertEqual(issues[0]["etiquetas"], ["fonte"])
        self.assertEqual(state["pistas"], [])

    def test_source_back_resets_failures(self):
        config = {"fontes": {"dr2": {"tipo": "rss", "url": "https://dr/serie2.xml"}}, "temas": CONFIG["temas"]}
        fetch, exists = pages()
        state = vigia.empty_state()
        state["falhas"]["dr2"] = ["2027-01-03", "2027-01-04"]
        state, _ = vigia.daily(state, config, fetch, exists, NOW)
        self.assertNotIn("dr2", state["falhas"])

    def test_weekly_with_leads_makes_one_issue_and_empties(self):
        fetch, exists = pages()
        state, _ = vigia.daily(vigia.empty_state(), CONFIG, fetch, exists, NOW)
        issue = vigia.weekly(state, NOW)
        self.assertEqual(issue["tipo"], "criar")
        self.assertEqual(issue["titulo"], "Novidades da semana (2027-01-05)")
        self.assertEqual(issue["etiquetas"], ["novidade"])
        self.assertFalse(issue["fechar"])
        self.assertIn("https://diariodarepublica.pt/dr/detalhe/despacho/1-a-2027-1", issue["corpo"])
        self.assertIn("```json", issue["corpo"])
        self.assertEqual(state["pistas"], [])
        self.assertIsNone(vigia.weekly(state, NOW))

    def test_failed_first_circular_run_does_not_flood_next_run(self):
        calls = {"n": 0}
        def flaky(url):
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError("falhou a meio")
            return url.rsplit("/", 1)[-1] in ("Circular_1_2027.pdf", "Circular_2_2027.pdf")
        fetch, _ = pages()
        state, _ = vigia.daily(vigia.empty_state(), CONFIG, fetch, flaky, NOW)
        self.assertEqual(state["falhas"].get("at"), ["2027-01-05"])
        self.assertFalse(state["fontes"]["at"].get("ultimas"))
        self.assertEqual(state["pistas"] and [p for p in state["pistas"] if p["fonte"] == "at"], [])
        _, exists = pages(circulars=("Circular_1_2027.pdf", "Circular_2_2027.pdf"))
        state, _ = vigia.daily(state, CONFIG, fetch, exists, NOW + datetime.timedelta(days=1))
        self.assertEqual([p for p in state["pistas"] if p["fonte"] == "at"], [])
        self.assertEqual(state["fontes"]["at"]["ultimas"]["2027"], 2)

    def test_december_error_in_next_year_keeps_state_unchanged(self):
        dec = datetime.datetime(2026, 12, 20, 6, 0, tzinfo=datetime.timezone.utc)
        fetch, _ = pages()
        state = vigia.empty_state()
        state["fontes"]["at"] = {"ultimas": {"2026": 4}}
        def exists(url):
            if "_2027" in url:
                raise OSError("falhou")
            return url.rsplit("/", 1)[-1] == "Circular_5_2026.pdf"
        state, _ = vigia.daily(state, CONFIG, fetch, exists, dec)
        self.assertEqual(state["fontes"]["at"]["ultimas"], {"2026": 4})
        self.assertEqual([p for p in state["pistas"] if p["fonte"] == "at"], [])
        self.assertIn("at", state["falhas"])

    def test_circular_probe_stops_at_the_cap(self):
        fetch, _ = pages()
        state = vigia.empty_state()
        state["fontes"]["at"] = {"ultimas": {"2027": 1}}
        state, _ = vigia.daily(state, CONFIG, fetch, lambda url: True, NOW)
        leads = [p for p in state["pistas"] if p["fonte"] == "at"]
        self.assertEqual(len(leads), vigia.MAX_CIRCULARS_PER_RUN)
        self.assertEqual(state["fontes"]["at"]["ultimas"]["2027"], 1 + vigia.MAX_CIRCULARS_PER_RUN)

    def test_first_run_with_an_always_true_probe_terminates(self):
        fetch, _ = pages()
        state, _ = vigia.daily(vigia.empty_state(), CONFIG, fetch, lambda url: True, NOW)
        self.assertEqual([p for p in state["pistas"] if p["fonte"] == "at"], [])
        self.assertEqual(state["fontes"]["at"]["ultimas"]["2027"], vigia.MAX_CIRCULARS_FIRST_RUN)

    def test_exists_requires_a_pdf(self):
        class Resp:
            def __init__(self, kind):
                self.status = 200
                self.headers = {"Content-Type": kind}
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        original = vigia.urllib.request.urlopen
        try:
            vigia.urllib.request.urlopen = lambda req, timeout=0: Resp("application/pdf")
            self.assertTrue(vigia.exists("https://x/a.pdf"))
            vigia.urllib.request.urlopen = lambda req, timeout=0: Resp("text/html; charset=utf-8")
            self.assertFalse(vigia.exists("https://x/a.pdf"))
        finally:
            vigia.urllib.request.urlopen = original

    def test_rss_only_remembers_links_that_became_leads(self):
        fetch, exists = pages()
        state, _ = vigia.daily(vigia.empty_state(), CONFIG, fetch, exists, NOW)
        self.assertEqual(list(state["fontes"]["dr2"]["vistos"]),
                         ["https://diariodarepublica.pt/dr/detalhe/despacho/1-a-2027-1"])
        state, _ = vigia.daily(state, CONFIG, fetch, exists, NOW + datetime.timedelta(days=1))
        self.assertEqual(len([p for p in state["pistas"] if p["fonte"] == "dr2"]), 1)

    def test_weekly_long_body_keeps_only_the_json_block(self):
        leads = [{"temas": ["irs"], "titulo": "T" * 200, "resumo": "R" * 500, "link": f"https://x/{i}",
                  "fonte": "dr2", "vistaEm": "2027-01-04"} for i in range(60)]
        state = vigia.empty_state()
        state["pistas"] = leads
        issue = vigia.weekly(state, NOW)
        self.assertIn("Lista longa: ver o bloco JSON.", issue["corpo"])
        self.assertIn("```json", issue["corpo"])
        self.assertNotIn("- **[irs]**", issue["corpo"])

    def test_cli_writes_state_and_issues(self):
        d = Path(tempfile.mkdtemp())
        (d / "vigia.json").write_text(json.dumps(CONFIG), encoding="utf-8")
        state = vigia.empty_state()
        state["pistas"] = [{"temas": ["irs"], "titulo": "T", "resumo": "", "link": "https://x", "fonte": "dr2", "vistaEm": "2027-01-04"}]
        (d / "estado.json").write_text(json.dumps(state), encoding="utf-8")
        vigia.main(["semanal", "--config", str(d / "vigia.json"), "--estado", str(d / "estado.json"), "--issues", str(d / "issues.json")])
        self.assertEqual(json.loads((d / "estado.json").read_text())["pistas"], [])
        self.assertEqual(len(json.loads((d / "issues.json").read_text())), 1)


if __name__ == "__main__":
    unittest.main()
