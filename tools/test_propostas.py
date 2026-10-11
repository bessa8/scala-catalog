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
        self.assertEqual(out, "ramo=claude/atualizacao-2026-10-11\nespelhar=false\n")

    def test_ver_mirror_stale(self):
        self.assertEqual(self.run_ver(ls((A, "main")), B), "ramo=\nespelhar=true\n")

    def test_ver_without_main(self):
        self.assertEqual(self.run_ver("", A), "ramo=\nespelhar=true\n")


if __name__ == "__main__":
    unittest.main()
