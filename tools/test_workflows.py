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

    def test_vigia_saves_state_before_firing_the_routine(self):
        text = read("vigia.yml")
        opening = text[text.index("- name: Abrir issues"):text.index("- name: Guardar o estado")]
        self.assertIn('--criadas "$RUNNER_TEMP/criadas.json"', opening)
        saving = text.index("- name: Guardar o estado")
        firing = text.index("python3 tools/disparar.py")
        self.assertLess(saving, firing)
        step = text[text.index("- name: Disparar a rotina"):]
        self.assertIn("steps.modo.outputs.modo == 'semanal'", step)
        self.assertIn('--criadas "$RUNNER_TEMP/criadas.json"', step)
        self.assertIn("ROTINA_URL: ${{ secrets.ROTINA_URL }}", step)
        self.assertIn("ROTINA_TOKEN: ${{ secrets.ROTINA_TOKEN }}", step)

    def test_rotina_only_for_bessa8_and_never_interpolates_into_the_script(self):
        text = read("rotina.yml")
        self.assertRegex(text, r"(?m)^permissions:\n  contents: read$")
        self.assertIn("types: [labeled]", text)
        self.assertIn("github.event.label.name == 'rever'", text)
        self.assertIn("github.event.sender.login == 'bessa8'", text)
        self.assertIn("github.actor == 'bessa8'", text)
        self.assertIn("NUMERO: ${{ github.event.issue.number || inputs.numero }}", text)
        script = text[text.index("run: python3 tools/disparar.py"):]
        self.assertNotIn("${{", script.splitlines()[0])
        self.assertIn('--issue "$NUMERO"', script)
        self.assertIn("ROTINA_URL: ${{ secrets.ROTINA_URL }}", text)
        self.assertIn("ROTINA_TOKEN: ${{ secrets.ROTINA_TOKEN }}", text)

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
