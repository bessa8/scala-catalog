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
        self.assertIn("GH_TOKEN: ${{ github.token }}", step)  # a Action lê a issue e manda-a no disparo

    def test_rotina_only_for_bessa8_and_never_interpolates_into_the_script(self):
        text = read("rotina.yml")
        self.assertRegex(text, r"(?m)^permissions:\n  contents: read\n  issues: read$")
        self.assertIn("GH_TOKEN: ${{ github.token }}", text[text.index("- name: Disparar a rotina"):])
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

    def step(self, job_text, name):
        """O texto do passo `name` de um job."""
        start = job_text.index(f"      - name: {name}\n")
        end = job_text.find("\n      - ", start + 1)
        return job_text[start:] if end < 0 else job_text[start:end]

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
        self.assertIn("invalidos: ${{ steps.ver.outputs.invalidos }}", ver)
        self.assertIn('git ls-remote --heads "$PROPOSTAS_HTTPS" > "$RUNNER_TEMP/ls.txt"', ver)
        self.assertIn("::warning::Repositório das propostas inacessível", ver)
        self.assertIn('python3 -I tools/propostas.py ver --ls-remote "$RUNNER_TEMP/ls.txt" --main "$(git rev-parse HEAD)"', ver)

    def test_publicar_job_runs_only_with_work_in_the_propostas_environment(self):
        text = read("publicar.yml")
        publicar = self.job(text, "publicar")
        self.assertEqual(text.count("environment: propostas"), 1)
        self.assertIn("environment: propostas", publicar)
        self.assertIn("needs: ver", publicar)
        self.assertIn("if: needs.ver.outputs.ramo != '' || needs.ver.outputs.espelhar == 'true' || "
                      "(needs.ver.outputs.invalidos != '' && needs.ver.outputs.invalidos != '0')", publicar)
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
        for name in ("Espelhar o main", "Apagar os ramos de nome inválido", "Nome do ramo", "Trazer o ramo",
                     "Conferir os caminhos", "Preparar o ramo", "Portão", "Validar", "Juntar ao main",
                     "Publicar o Pages", "Issues", "Espelhar e apagar o ramo", "Avisar a falha"):
            self.assertIn("steps.chave.outputs.pronto == 'true'", self.step(publicar, name), name)

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
        self.assertIn('run: python3 -I confiavel/tools/propostas.py nome "$RAMO"', self.step(publicar, "Nome do ramo"))
        prepare = self.step(publicar, "Preparar o ramo")
        self.assertIn("git checkout -B proposta refs/remotes/propostas/ramo", prepare)
        self.assertIn("git config user.name scala-publicar", prepare)
        self.assertIn("git config user.email 41898282+github-actions[bot]@users.noreply.github.com", prepare)
        self.assertIn('git rebase "$BASE"', prepare)
        # só os passos do ramo dependem dele; o espelho e a limpeza dos nomes inválidos não
        for name in ("Nome do ramo", "Trazer o ramo", "Conferir os caminhos", "Preparar o ramo", "Portão", "Validar",
                     "Juntar ao main", "Publicar o Pages", "Issues", "Espelhar e apagar o ramo"):
            self.assertIn("needs.ver.outputs.ramo != ''", self.step(publicar, name), name)
        for name in ("Espelhar o main", "Apagar os ramos de nome inválido"):
            self.assertNotIn("needs.ver.outputs.ramo", self.step(publicar, name), name)
        self.assertIn('git push --force "$PROPOSTAS_SSH" HEAD:refs/heads/main', self.step(publicar, "Espelhar o main"))

    def test_publicar_fetch_never_follows_tags_and_the_base_is_pinned(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        fixar = self.step(publicar, "Fixar a base")
        self.assertIn("BASE=$(git rev-parse --verify 'refs/remotes/origin/main^{commit}')", fixar)
        self.assertIn('echo "BASE=$BASE" >> "$GITHUB_ENV"', fixar)
        self.assertIn('git for-each-ref refs/tags > "$RUNNER_TEMP/tags-antes.txt"', fixar)
        fetch = self.step(publicar, "Trazer o ramo")
        self.assertIn('git fetch --no-tags "$PROPOSTAS_SSH" "refs/heads/$RAMO:refs/remotes/propostas/ramo"', fetch)
        self.assertIn('git for-each-ref refs/tags | diff -q - "$RUNNER_TEMP/tags-antes.txt"', fetch)
        self.assertEqual(publicar.count("git fetch"), 1)
        # a base fixa-se antes de qualquer fetch das propostas e o ramo vem antes do espelho
        self.assertLess(publicar.index("- name: Fixar a base"), publicar.index("- name: Trazer o ramo"))
        self.assertLess(publicar.index("- name: Trazer o ramo"), publicar.index("- name: Espelhar o main"))
        # depois de fixada a base, nenhum nome curto origin/main (só o caminho completo refs/remotes/origin/main)
        after = publicar[publicar.index("- name: Nome do ramo"):]
        self.assertNotRegex(after, r"(?<!remotes/)origin/main")
        self.assertIn('--base "$BASE"', self.step(publicar, "Portão"))
        self.assertIn('--desde "$BASE"', self.step(publicar, "Validar"))

    def test_publicar_checks_the_paths_before_any_checkout_and_neutralises_lfs(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        paths = self.step(publicar, "Conferir os caminhos")
        self.assertIn('git diff --name-only -z "$BASE"...refs/remotes/propostas/ramo > "$RUNNER_TEMP/caminhos.bin"', paths)
        self.assertIn('python3 -I confiavel/tools/propostas.py caminhos "$RUNNER_TEMP/caminhos.bin"', paths)
        self.assertLess(publicar.index("- name: Conferir os caminhos"), publicar.index("git checkout -B proposta"))
        self.assertEqual(publicar.count("git checkout"), 1)
        env = publicar[publicar.index("    env:\n"):publicar.index("    steps:\n")]
        self.assertIn("GIT_LFS_SKIP_SMUDGE: '1'", env)
        self.assertIn("GIT_CONFIG_COUNT: '4'", env)
        for n, (key, value) in enumerate((("filter.lfs.process", "''"), ("filter.lfs.smudge", "''"),
                                          ("filter.lfs.clean", "''"), ("filter.lfs.required", "'false'"))):
            self.assertIn(f"GIT_CONFIG_KEY_{n}: {key}\n      GIT_CONFIG_VALUE_{n}: {value}\n", env)

    def test_publicar_python_runs_isolated(self):
        text = read("publicar.yml")
        for script in self.run_scripts(text):
            self.assertNotIn("python3 -c", script)
            for line in script.splitlines():
                if re.search(r"python3 (?!-I)", line):
                    # os scripts do portão correm em modo de script (confiavel/tools/x.py); o resto leva -I
                    self.assertRegex(line, r"python3 confiavel/tools/(portao|catalog|plausivel|relatorio|issues)\.py", line)
        for sub in ("nome", "caminhos", "invalidos"):
            self.assertIn(f"python3 -I confiavel/tools/propostas.py {sub}", text)

    def test_publicar_gate_and_merge_run_the_trusted_scripts(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        self.assertIn('python3 confiavel/tools/portao.py --base "$BASE"', publicar)
        self.assertRegex(publicar, r"- name: Juntar ao main\n        id: juntar\n")
        merge = self.step(publicar, "Juntar ao main")
        self.assertIn('[ "$(git rev-parse refs/remotes/origin/main)" != "$BASE" ]', merge)
        self.assertIn('git merge-base --is-ancestor "$BASE" HEAD', merge)
        self.assertIn("git push origin HEAD:refs/heads/main", merge)
        self.assertLess(merge.index("merge-base"), merge.index("git push"))
        self.assertNotIn("python3 tools/", publicar)  # nunca scripts do ramo
        deleting = self.step(publicar, "Espelhar e apagar o ramo")
        self.assertIn('git push --atomic --force "$PROPOSTAS_SSH" HEAD:refs/heads/main ":refs/heads/$RAMO"', deleting)

    def test_publicar_mirror_failure_does_not_stop_the_branch_and_is_reported_once(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        mirror = self.step(publicar, "Espelhar o main")
        self.assertIn("id: espelhar", mirror)
        self.assertIn("continue-on-error: true", mirror)
        other = self.step(publicar, "Avisar outra falha")
        self.assertIn("steps.espelhar.outcome == 'failure'", other)
        self.assertIn("failure() && needs.ver.outputs.ramo == ''", other)

    def test_publicar_deletes_invalid_branches_in_one_push_without_issues(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        step = self.step(publicar, "Apagar os ramos de nome inválido")
        self.assertIn("needs.ver.outputs.invalidos != '0'", step)
        self.assertIn("continue-on-error: true", step)
        self.assertIn('python3 -I confiavel/tools/propostas.py invalidos --ls-remote "$RUNNER_TEMP/ls-ssh.txt"', step)
        self.assertIn('APAGAR+=(":refs/heads/$NOME")', step)
        self.assertIn('git push "$PROPOSTAS_SSH" "${APAGAR[@]}"', step)
        self.assertEqual(step.count("git push"), 1)
        self.assertIn("::warning::", step)
        self.assertNotIn("gh issue", step)
        self.assertNotIn("${{", step[step.index("run: |"):])
        # os nomes nunca vão para o registo nem para as issues: só a contagem
        for line in step.splitlines():
            if "echo" in line:
                self.assertNotIn("$NOME", line)
                self.assertNotIn("${NOMES[@]}", line.replace("${#NOMES[@]}", ""))

    def test_publicar_failure_message_depends_on_whether_the_merge_happened(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        failure = self.step(publicar, "Avisar a falha")
        self.assertIn("if: failure() && steps.chave.outputs.pronto == 'true' && needs.ver.outputs.ramo != ''", failure)
        self.assertIn("JUNTAR: ${{ steps.juntar.outcome }}", failure)
        self.assertIn("RAMO: ${{ needs.ver.outputs.ramo }}", failure)
        script = failure[failure.index("run: |"):]
        self.assertNotIn("${{", script)  # nada de expressões dentro do script: tudo por variáveis de ambiente
        self.assertIn('[ "$JUNTAR" = "success" ]', script)
        self.assertIn("O ramo já foi juntado ao main; falhou um passo seguinte (Pages, issues ou apagar o ramo)", script)
        self.assertIn("O ramo ficou por juntar", script)
        self.assertIn('TITULO="Precisa de ti: a publicação de $RAMO falhou"', script)

    def test_publicar_failure_moves_the_branch_first_and_says_what_happened(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        script = self.step(publicar, "Avisar a falha")
        move = script.index('"refs/remotes/propostas/ramo:refs/heads/recusados/$RAMO"')
        self.assertLess(move, script.index("gh issue create"))
        self.assertIn("git push --atomic --force", script[move - 60:move])
        self.assertIn('DESTINO="O ramo foi movido para recusados/$RAMO no repositório das propostas."', script)
        self.assertIn('DESTINO="O ramo foi apagado do repositório das propostas."', script)
        self.assertIn('DESTINO="O ramo ficou no repositório das propostas."', script)
        self.assertIn('--body "$ESTADO $DESTINO Ver $RUN_URL"', script)
        # só apaga quando o ramo não foi trazido e o nome é inválido; um ramo válido nunca se apaga por um fetch falhado
        self.assertIn("git rev-parse --verify -q refs/remotes/propostas/ramo", script)
        self.assertIn('elif ! python3 -I confiavel/tools/propostas.py nome "$RAMO" && git push "$PROPOSTAS_SSH" ":refs/heads/$RAMO"', script)
        # uma só issue aberta por ramo: se já houver, comenta nela; o erro fica no registo antes das issues
        self.assertLess(script.index("gh issue list --state open --search"), script.index("gh issue create"))
        self.assertIn('select(.title == \\"$TITULO\\")', script)
        self.assertIn('if [ -z "$JA" ]', script)
        self.assertIn('gh issue comment "$JA"', script)
        self.assertLess(script.index('echo "::error::$ESTADO $DESTINO"'), script.index("gh issue list"))

    def test_publicar_other_failure_opens_a_single_issue(self):
        publicar = self.job(read("publicar.yml"), "publicar")
        other = publicar[publicar.index("- name: Avisar outra falha"):]
        self.assertIn("if: (failure() && needs.ver.outputs.ramo == '') || steps.espelhar.outcome == 'failure'", other)
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
