import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import propostas  # noqa: E402

A = "a" * 40
B = "b" * 40


def ls(*pares):
    return "".join(f"{sha}\trefs/heads/{nome}\n" for sha, nome in pares)


class PropostasTest(unittest.TestCase):
    def test_escolher_takes_the_first_claude_branch_alphabetically(self):
        texto = ls((A, "main"), (B, "claude/atualizacao-2026-10-12"), (A, "claude/atualizacao-2026-10-11-2"),
                   (B, "claude/atualizacao-2026-10-11"))
        self.assertEqual(propostas.escolher(texto), "claude/atualizacao-2026-10-11")

    def test_escolher_without_claude_branches(self):
        self.assertIsNone(propostas.escolher(""))
        self.assertIsNone(propostas.escolher(ls((A, "main"))))
        self.assertIsNone(propostas.escolher(ls((A, "main"), (B, "recusados/claude/atualizacao-2026-10-11"))))

    def test_escolher_ignores_garbage_lines(self):
        texto = "\nlixo\n" + A + " refs/heads/claude/x\n" + A + "\trefs/tags/claude/y\n" + A + "\trefs/heads/\n" \
            + ls((B, "claude/atualizacao-2026-10-11"))
        self.assertEqual(propostas.escolher(texto), "claude/atualizacao-2026-10-11")

    def test_nome_valido(self):
        for ok in ("claude/atualizacao-2026-10-11", "claude/atualizacao-2026-10-11-2", "claude/atualizacao-2026-10-11-12"):
            self.assertTrue(propostas.nome_valido(ok), ok)
        for mau in ("claude/atualizacao-2026-10-11-", "claude/atualizacao-2026-10-11 x", "claude/atualizacao-2026-10-11\n",
                    "claude/atualizacao-2026-10-11/..", "claude/../main", "claude/atualizacao-2026-10-11-a",
                    "outro/atualizacao-2026-10-11", "claude/atualizacao-26-10-11", " claude/atualizacao-2026-10-11", ""):
            self.assertFalse(propostas.nome_valido(mau), repr(mau))

    def test_sha_do_main(self):
        self.assertEqual(propostas.sha_do_main(ls((B, "claude/x"), (A, "main"))), A)
        self.assertIsNone(propostas.sha_do_main(ls((B, "claude/x"))))
        self.assertIsNone(propostas.sha_do_main(ls((B, "mainx"))))

    def run_ver(self, texto, main):
        with tempfile.TemporaryDirectory() as d:
            ficheiro, saida = Path(d, "ls.txt"), Path(d, "saida.txt")
            ficheiro.write_text(texto, encoding="utf-8")
            r = subprocess.run([sys.executable, str(Path(propostas.__file__)), "ver", "--ls-remote", str(ficheiro),
                                "--main", main, "--github-output", str(saida)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return saida.read_text(encoding="utf-8")

    def test_ver_mirror_up_to_date(self):
        out = self.run_ver(ls((A, "main"), (B, "claude/atualizacao-2026-10-11")), A)
        self.assertEqual(out, "ramo=claude/atualizacao-2026-10-11\nespelhar=false\ninvalidos=0\n")

    def test_ver_mirror_stale(self):
        self.assertEqual(self.run_ver(ls((A, "main")), B), "ramo=\nespelhar=true\ninvalidos=0\n")

    def test_ver_without_main(self):
        self.assertEqual(self.run_ver("", A), "ramo=\nespelhar=true\ninvalidos=0\n")

    def test_escolher_skips_invalid_names_and_ver_counts_them(self):
        texto = ls((A, "main"), (B, "claude/!0"), (B, "claude/@alguem"), (B, "claude/atualizacao-2026-10-11-x"),
                   (B, "claude/atualizacao-2026-10-12"))
        self.assertEqual(propostas.escolher(texto), "claude/atualizacao-2026-10-12")
        self.assertEqual(propostas.invalidos(texto), ["claude/!0", "claude/@alguem", "claude/atualizacao-2026-10-11-x"])
        self.assertEqual(self.run_ver(texto, A), "ramo=claude/atualizacao-2026-10-12\nespelhar=false\ninvalidos=3\n")

    def test_only_invalid_names_means_no_branch(self):
        texto = ls((A, "main"), (B, "claude/lixo"))
        self.assertIsNone(propostas.escolher(texto))
        self.assertEqual(self.run_ver(texto, A), "ramo=\nespelhar=false\ninvalidos=1\n")

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(Path(propostas.__file__)), *args], capture_output=True, text=True)

    def test_invalidos_command_lists_one_name_per_line(self):
        with tempfile.TemporaryDirectory() as d:
            ficheiro, saida = Path(d, "ls.txt"), Path(d, "inv.txt")
            ficheiro.write_text(ls((A, "main"), (B, "claude/b"), (B, "claude/a"), (B, "claude/atualizacao-2026-10-11")),
                                encoding="utf-8")
            r = self.run_cli("invalidos", "--ls-remote", str(ficheiro), "--saida", str(saida))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(saida.read_text(encoding="utf-8"), "claude/a\nclaude/b\n")

    def test_nome_command(self):
        self.assertEqual(self.run_cli("nome", "claude/atualizacao-2026-10-11-2").returncode, 0)
        r = self.run_cli("nome", "claude/$(x)")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("$(x)", r.stdout + r.stderr)  # o nome não vai para o registo

    def test_caminhos_command_only_allows_what_the_gate_allows(self):
        def run(*nomes):
            with tempfile.TemporaryDirectory() as d:
                ficheiro = Path(d, "caminhos.bin")
                ficheiro.write_bytes(b"".join(n.encode() + b"\0" for n in nomes))
                return self.run_cli("caminhos", str(ficheiro))
        self.assertEqual(run("tables/tru.2027-01-01.json", "tax/irs.2027-01-01.json", "relatorios/2026-10-11.json",
                             "manifest.json", "VERIFICAR.md", "por-confirmar.md").returncode, 0)
        self.assertEqual(run().returncode, 0)
        for mau in (".gitattributes", ".lfsconfig", "tools/portao.py", ".github/workflows/x.yml", "ROTINA.md",
                    "tables/../tools/x.py", "tables/a b.json", "tables/$(x).json", "confiavel/x.json", "tables//x.json"):
            r = run("manifest.json", mau)
            self.assertNotEqual(r.returncode, 0, mau)
            self.assertNotIn(mau, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
