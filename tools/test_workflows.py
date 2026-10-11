"""Confere o que interessa dos workflows (não há PyYAML; leitura como texto)."""
import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def read(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


class WorkflowsTest(unittest.TestCase):
    def test_validar_is_read_only_and_ignores_routine_branches(self):
        text = read("validar.yml")
        self.assertRegex(text, r"(?m)^permissions:\n  contents: read$")
        self.assertIn("branches-ignore: ['claude/**']", text)
        self.assertRegex(text, r"(?m)^  pull_request:$")
        self.assertNotIn("on: [push, pull_request]", text)

    def test_vigia_reads_twice_a_day_and_detects_weekly_on_mondays(self):
        text = read("vigia.yml")
        self.assertIn("cron: '0 6 * * *'", text)
        self.assertIn("cron: '0 21 * * *'", text)
        self.assertIn("cron: '0 7 * * 1'", text)
        self.assertIn('[ "$AGENDA" = "0 7 * * 1" ]', text)  # só a segunda de manhã é semanal

    def test_vigia_lists_open_issues_before_reading_and_only_in_weekly_mode(self):
        text = read("vigia.yml")
        listing = text.index("gh issue list --state open")
        reading = text.index("python3 tools/vigia.py semanal")
        self.assertLess(listing, reading)
        self.assertIn("if: steps.modo.outputs.modo == 'semanal'", text)
        self.assertIn("GH_TOKEN: ${{ github.token }}", text[text.index("Listar as issues abertas"):reading])
        self.assertIn("--abertas", text[reading:reading + 200])
        self.assertEqual(text.count("--abertas"), 1)  # o modo diário não leva a listagem
        self.assertIn("updatedAt", text[listing:listing + 200])

    def test_publicar_failure_message_depends_on_whether_the_merge_happened(self):
        text = read("publicar.yml")
        self.assertRegex(text, r"- name: Juntar ao main\n        id: juntar\n")
        failure = text[text.index("- name: Avisar a falha"):]
        self.assertIn("JUNTAR: ${{ steps.juntar.outcome }}", failure)
        script = failure[failure.index("run: |"):]
        self.assertNotIn("${{", script)  # nada de expressões dentro do script: tudo por variáveis de ambiente
        self.assertIn('[ "$JUNTAR" = "success" ]', script)
        self.assertIn("O ramo já foi juntado ao main; falhou um passo seguinte (Pages, issues ou apagar o ramo)", script)
        self.assertIn("O ramo ficou por juntar", script)

    def test_every_workflow_declares_permissions(self):
        for path in WORKFLOWS.glob("*.yml"):
            self.assertRegex(path.read_text(encoding="utf-8"), r"(?m)^permissions:\n", path.name)


if __name__ == "__main__":
    unittest.main()
