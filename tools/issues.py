#!/usr/bin/env python3
"""Abre e fecha issues do GitHub a partir de uma lista JSON (com o `gh`).

    python3 tools/issues.py FICHEIRO [--criadas SAIDA]

Com --criadas, escreve em SAIDA a lista das issues abertas: [{"numero", "titulo", "etiquetas"}].
Cada entrada: {"tipo": "criar", "titulo", "corpo", "etiquetas": [...], "fechar": bool}
ou {"tipo": "fechar", "numero": N, "comentario": "..."}. Sem FICHEIRO, nada a fazer.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def gh(args, stdin=None):
    r = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=True)
    return r.stdout.strip()


CLOSABLE_LABELS = ("novidade", "rever")


def _check_closable(action, gh):
    """Só se fecha uma issue aberta das que a rotina trata (etiqueta novidade ou rever)."""
    n = action.get("numero")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise ValueError(f"número de issue inválido: {n!r}")
    try:
        info = json.loads(gh(["issue", "view", str(n), "--json", "state,labels"]))
        state = info["state"]
        names = {label["name"] for label in info["labels"]}
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"não consegui ler a issue #{n}: {e!r}")
    if state != "OPEN":
        raise ValueError(f"a issue #{n} não está aberta; não a fecho")
    if not names & set(CLOSABLE_LABELS):
        raise ValueError(f"a issue #{n} não tem a etiqueta novidade nem rever; não a fecho")


def run(actions, gh=gh):
    for a in actions:  # valida tudo antes de mexer no GitHub
        if a.get("tipo") not in ("criar", "fechar"):
            raise ValueError(f"ação desconhecida: {a.get('tipo')}")
    for a in actions:
        if a["tipo"] == "fechar":
            _check_closable(a, gh)
    labels = sorted({label for a in actions if a["tipo"] == "criar" for label in a.get("etiquetas", [])})
    for label in labels:
        gh(["label", "create", label, "--force"])
    criadas = []
    for a in actions:
        if a["tipo"] == "criar":
            args = ["issue", "create", "--title", a["titulo"], "--body-file", "-"]
            for label in a.get("etiquetas", []):
                args += ["--label", label]
            url = gh(args, stdin=a["corpo"])
            criadas.append({"numero": int(url.rsplit("/", 1)[-1]), "titulo": a["titulo"],
                            "etiquetas": list(a.get("etiquetas", []))})
            if a.get("fechar"):
                gh(["issue", "close", url.rsplit("/", 1)[-1]])
        else:
            gh(["issue", "close", str(a["numero"]), "--comment", a["comentario"]])
    return criadas


def main(argv=None):
    parser = argparse.ArgumentParser(description="Abre e fecha issues a partir de uma lista JSON.")
    parser.add_argument("ficheiro", nargs="?")
    parser.add_argument("--criadas")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not args.ficheiro or not Path(args.ficheiro).exists():
        if args.criadas:
            Path(args.criadas).write_text("[]\n", encoding="utf-8")
        return
    try:
        actions = json.loads(Path(args.ficheiro).read_text(encoding="utf-8"))
        if not isinstance(actions, list) or not all(isinstance(a, dict) for a in actions):
            raise ValueError("tem de ser uma lista de ações")
        criadas = run(actions)
        if args.criadas:
            Path(args.criadas).write_text(json.dumps(criadas, ensure_ascii=False) + "\n", encoding="utf-8")
    except subprocess.CalledProcessError as e:
        print(f"o gh falhou ({' '.join(e.cmd[:3])}): {(e.stderr or '').strip()}")
        sys.exit(1)
    except (OSError, ValueError, KeyError) as e:
        print(f"lista de issues inválida ({args.ficheiro}): {e!r}")
        sys.exit(1)


if __name__ == "__main__":
    main()
