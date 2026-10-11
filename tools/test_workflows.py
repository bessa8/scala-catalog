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
        self.assertRegex(text, r"(?m)^concurrency:\n  group: rotina\n  cancel-in-progress: false$")
        self.assertIn("persist-credentials: false", text)

    def job(self, text, name):
        """O texto do job `name` (do cabeçalho `  name:` ao seguinte, ou ao fim)."""
        start = text.index(f"\n  {name}:\n") + 1
        following = re.search(r"(?m)^  [a-z]+:\n", text[start + 1:])
        return text[start:start + 1 + following.start()] if following else text[start:]

    def run_scripts(self, text):
        """O texto de cada `run:` (numa linha ou em bloco)."""
        lines, scripts, i = text.splitlines(), [], 0
        while i < len(lines):
            m = re.match(r"(\s*)(?:- )?run:\s*(.*)$", lines[i])
            i += 1
            if not m:
                continue
            indent, body = len(m.group(1)), [m.group(2)]
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
                body.append(lines[i])
                i += 1
            scripts.append("\n".join(body))
        return scripts

    def test_publicar_runs_hourly_from_main_and_never_on_push(self):
        text = read("publicar.yml")
        on = text[text.index("\non:\n"):text.index("\npermissions:\n")]
        self.assertNotIn("push:", on)
        self.assertIn("schedule:", on)
        self.assertIn("- cron: '17 * * * *'", on)
        self.assertIn("workflow_dispatch:", on)
        self.assertRegex(text, r"(?m)^permissions:\n  contents: write\n  issues: write\n  actions: write\n")
        self.assertRegex(text, r"(?m)^concurrency:\n  group: main\n  cancel-in-progress: false$")
        self.assertIn("PROPOSTAS_HTTPS: https://github.com/bessa8/scala-catalog-propostas.git", text)
        self.assertIn("PROPOSTAS_SSH: git@github.com:bessa8/scala-catalog-propostas.git", text)

    def test_publicar_ver_job_is_read_only_without_secrets(self):
        ver = self.job(read("publicar.yml"), "ver")
        self.assertIn("if: github.ref == 'refs/heads/main'", ver)
        self.assertIn("permissions:\n      contents: read", ver)
        self.assertIn("timeout-minutes: 5", ver)
        self.assertNotIn("secrets.", ver)
        self.assertNotIn("environment:", ver)
        self.assertIn("persist-credentials: false", ver)
        self.assertIn("ramo: ${{ steps.ver.outputs.ramo }}", ver)
        self.assertIn("espelhar: ${{ steps.ver.outputs.espelhar }}", ver)
        self.assertIn('git ls-remote --heads "$PROPOSTAS_HTTPS" > "$RUNNER_TEMP/ls.txt"', ver)
        self.assertIn("::warning::Repositório das propostas inacessível", ver)
        self.assertIn('python3 tools/propostas.py ver --ls-remote "$RUNNER_TEMP/ls.txt" --main "$(git rev-parse HEAD)"', ver)

    def test_publicar_job_runs_only_with_work_in_the_propostas_environment(self):
        text = read("publicar.yml")
        publicar = self.job(text, "publicar")
        self.assertEqual(text.count("environment: propostas"), 1)
        self.assertIn("environment: propostas", publicar)
        self.assertIn("needs: ver", publicar)
        self.assertIn("if: needs.ver.outputs.ramo != '' || needs.ver.outputs.espelhar == 'true'", publicar)
        self.assertIn("timeout-minutes: 20", publicar)
        self.assertEqual(publicar.count("secrets."), 1)
        self.assertIn("CHAVE: ${{ secrets.PROPOSTAS_CHAVE }}", publicar)
        self.assertIn("path: confiavel", publicar)

    def test_publicar_ssh_key_uses_a_pinned_host_key(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        self.assertIn("github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl", publicar)
        self.assertIn("StrictHostKeyChecking=yes", publicar)
        self.assertNotIn("StrictHostKeyChecking=no", publicar)
        self.assertIn('chmod 600 "$RUNNER_TEMP/propostas"', publicar)
        self.assertIn("::warning::Falta o secret PROPOSTAS_CHAVE no ambiente propostas: nada publicado.", publicar)
        self.assertIn('echo "pronto=false" >> "$GITHUB_OUTPUT"', publicar)
        # todos os passos que usam o SSH esperam pela chave
        for name in ("Espelhar o main", "Nome do ramo", "Trazer o ramo", "Portão", "Validar", "Juntar ao main",
                     "Publicar o Pages", "Issues", "Espelhar e apagar o ramo", "Avisar a falha"):
            step = publicar[publicar.index(f"- name: {name}\n"):]
            step = step[:step.index("\n      - ", 1)] if "\n      - " in step[1:] else step
            self.assertIn("steps.chave.outputs.pronto == 'true'", step, name)

    def test_publicar_never_interpolates_expressions_into_scripts(self):
        scripts = self.run_scripts(self.job(read("publicar.yml"), "publicar"))
        self.assertGreater(len(scripts), 8)
        for script in scripts:
            self.assertNotIn("${{", script)  # tudo por variáveis de ambiente
        for script in self.run_scripts(self.job(read("publicar.yml"), "ver")):
            self.assertNotIn("${{", script)

    def test_publicar_branch_steps_pass_the_name_through_env_and_check_it(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        self.assertIn("RAMO: ${{ needs.ver.outputs.ramo }}", publicar)
        check = publicar[publicar.index("- name: Nome do ramo"):publicar.index("- name: Trazer o ramo")]
        self.assertIn("propostas.nome_valido(sys.argv[1])", check)
        self.assertIn('"$RAMO"', check)
        self.assertIn("confiavel/tools", check)
        fetch = publicar[publicar.index("- name: Trazer o ramo"):publicar.index("- name: Portão")]
        self.assertIn('git fetch "$PROPOSTAS_SSH" "refs/heads/$RAMO:refs/remotes/propostas/ramo"', fetch)
        self.assertIn("git checkout -B proposta refs/remotes/propostas/ramo", fetch)
        self.assertIn("git config user.name scala-publicar", fetch)
        self.assertIn("git config user.email 41898282+github-actions[bot]@users.noreply.github.com", fetch)
        self.assertIn("git rebase origin/main", fetch)
        # só os passos do ramo (do nome ao apagar) dependem dele
        for name in ("Nome do ramo", "Trazer o ramo", "Portão", "Validar", "Juntar ao main", "Publicar o Pages",
                     "Issues", "Espelhar e apagar o ramo"):
            step = publicar[publicar.index(f"- name: {name}\n"):]
            self.assertIn("needs.ver.outputs.ramo != ''", step.split("\n      - ")[0], name)
        mirror = publicar[publicar.index("- name: Espelhar o main"):publicar.index("- name: Nome do ramo")]
        self.assertIn('git push --force "$PROPOSTAS_SSH" HEAD:refs/heads/main', mirror)
        self.assertNotIn("needs.ver.outputs.ramo", mirror)

    def test_publicar_gate_and_merge_run_the_trusted_scripts(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        self.assertIn("python3 confiavel/tools/portao.py --base origin/main", publicar)
        self.assertRegex(publicar, r"- name: Juntar ao main\n        id: juntar\n")
        self.assertIn("run: git push origin HEAD:main", publicar)
        self.assertNotIn("python3 tools/", publicar)  # nunca scripts do ramo
        deleting = publicar[publicar.index("- name: Espelhar e apagar o ramo"):publicar.index("- name: Avisar a falha")]
        self.assertIn('git push --atomic --force "$PROPOSTAS_SSH" HEAD:refs/heads/main ":refs/heads/$RAMO"', deleting)

    def test_publicar_failure_message_depends_on_whether_the_merge_happened(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        failure = publicar[publicar.index("- name: Avisar a falha"):publicar.index("- name: Avisar outra falha")]
        self.assertIn("if: failure() && steps.chave.outputs.pronto == 'true' && needs.ver.outputs.ramo != ''", failure)
        self.assertIn("JUNTAR: ${{ steps.juntar.outcome }}", failure)
        self.assertIn("RAMO: ${{ needs.ver.outputs.ramo }}", failure)
        script = failure[failure.index("run: |"):]
        self.assertNotIn("${{", script)  # nada de expressões dentro do script: tudo por variáveis de ambiente
        self.assertIn('[ "$JUNTAR" = "success" ]', script)
        self.assertIn("O ramo já foi juntado ao main; falhou um passo seguinte (Pages, issues ou apagar o ramo)", script)
        self.assertIn("O ramo ficou por juntar", script)
        self.assertIn("Precisa de ti: a publicação de $RAMO falhou", script)
        self.assertIn("O ramo foi movido para recusados/$RAMO no repositório das propostas.", script)

    def test_publicar_failure_moves_the_branch_to_recusados_after_the_issue(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        script = publicar[publicar.index("- name: Avisar a falha"):publicar.index("- name: Avisar outra falha")]
        issue = script.index("gh issue create")
        move = script.index('"refs/remotes/propostas/ramo:refs/heads/recusados/$RAMO"')
        self.assertLess(issue, move)
        self.assertIn('":refs/heads/$RAMO"', script)
        self.assertIn('|| git push "$PROPOSTAS_SSH" ":refs/heads/$RAMO"', script)  # fetch que não chegou a acontecer

    def test_publicar_other_failure_opens_a_single_issue(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        other = publicar[publicar.index("- name: Avisar outra falha"):]
        self.assertIn("if: failure() && needs.ver.outputs.ramo == ''", other)
        self.assertIn("Precisa de ti: a Action Publicar falhou", other)
        self.assertIn("gh issue list --state open --search", other)
        self.assertIn("--json title", other)
        self.assertLess(other.index("gh issue list"), other.index("gh issue create"))
        self.assertNotIn("${{", other[other.index("run: |"):])

    def test_every_workflow_declares_permissions(self):
        for path in WORKFLOWS.glob("*.yml"):
            self.assertRegex(path.read_text(encoding="utf-8"), r"(?m)^permissions:\n", path.name)


if __name__ == "__main__":
    unittest.main()
