#!/usr/bin/env python3
"""Abre e fecha issues do GitHub a partir de uma lista JSON (com o `gh`).

    python3 tools/issues.py FICHEIRO

Cada entrada: {"tipo": "criar", "titulo", "corpo", "etiquetas": [...], "fechar": bool}
ou {"tipo": "fechar", "numero": N, "comentario": "..."}. Sem FICHEIRO, nada a fazer.
"""
import json
import subprocess
import sys
from pathlib import Path


def gh(args, stdin=None):
    r = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=True)
    return r.stdout.strip()


def run(actions, gh=gh):
    for a in actions:  # valida tudo antes de mexer no GitHub
        if a.get("tipo") not in ("criar", "fechar"):
            raise ValueError(f"ação desconhecida: {a.get('tipo')}")
    labels = sorted({label for a in actions if a["tipo"] == "criar" for label in a.get("etiquetas", [])})
    for label in labels:
        gh(["label", "create", label, "--force"])
    for a in actions:
        if a["tipo"] == "criar":
            args = ["issue", "create", "--title", a["titulo"], "--body-file", "-"]
            for label in a.get("etiquetas", []):
                args += ["--label", label]
            url = gh(args, stdin=a["corpo"])
            if a.get("fechar"):
                gh(["issue", "close", url.rsplit("/", 1)[-1]])
        else:
            gh(["issue", "close", str(a["numero"]), "--comment", a["comentario"]])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or not Path(argv[0]).exists():
        return
    try:
        actions = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
        if not isinstance(actions, list) or not all(isinstance(a, dict) for a in actions):
            raise ValueError("tem de ser uma lista de ações")
        run(actions)
    except subprocess.CalledProcessError as e:
        print(f"o gh falhou ({' '.join(e.cmd[:3])}): {(e.stderr or '').strip()}")
        sys.exit(1)
    except (OSError, ValueError, KeyError) as e:
        print(f"lista de issues inválida ({argv[0]}): {e!r}")
        sys.exit(1)


if __name__ == "__main__":
    main()
