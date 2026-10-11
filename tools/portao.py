#!/usr/bin/env python3
"""O portão de um ramo claude/…: só dados, nada apagado, um relatório novo.

    python3 tools/portao.py --base origin/main [--github-output FICHEIRO]

Falha sempre «para o lado seguro»: o que não for claramente permitido é recusado.
"""
import argparse
import json
import re
import subprocess
import sys

import relatorio

ALLOWED_PREFIXES = ("tables/", "tax/", "relatorios/")
ALLOWED_FILES = {"manifest.json", "VERIFICAR.md", "por-confirmar.md"}
DATA_PREFIXES = ("tables/", "tax/")
REPORT = re.compile(r"relatorios/[0-9]{4}-[0-9]{2}-[0-9]{2}(-[0-9]+)?\.json")  # AAAA-MM-DD[-N].json
SAFE_PATH = re.compile(r"[A-Za-z0-9._/-]+")  # nenhum caminho permitido pode trazer espaços, $, aspas ou controlos
FILE_MODE = "100644"  # ficheiro normal: sem ligações simbólicas, submódulos nem executáveis


def problems(changes):
    """changes: (estado, caminho) ou (estado, caminho, modo). Devolve (problemas, relatórios novos)."""
    out, reports = [], []
    for change in changes:
        status, path = change[0], change[1]
        mode = change[2] if len(change) > 2 else FILE_MODE
        if not SAFE_PATH.fullmatch(path) or any(part in ("", ".", "..") for part in path.split("/")):
            out.append(f"{path}: caminho suspeito")
        elif not (path.startswith(ALLOWED_PREFIXES) or path in ALLOWED_FILES):
            out.append(f"{path}: a rotina não pode mexer neste ficheiro")
        elif status.startswith("D"):
            out.append(f"{path}: a rotina não pode apagar ficheiros")
        elif status not in ("A", "M"):
            out.append(f"{path}: alteração não permitida ({status or '?'})")
        elif mode != FILE_MODE:
            out.append(f"{path}: modo {mode} não permitido (só ficheiros normais, sem ligações simbólicas nem executáveis)")
        elif path.startswith(DATA_PREFIXES) and not path.endswith(".json"):
            out.append(f"{path}: em tables/ e tax/ só entram ficheiros .json")
        elif path.startswith("relatorios/"):
            if status != "A" or not REPORT.fullmatch(path):
                out.append(f"{path}: em relatorios/ só se acrescenta um relatório novo chamado AAAA-MM-DD.json (ou AAAA-MM-DD-N.json)")
            else:
                reports.append(path)
    if len(reports) != 1:
        out.append(f"o ramo tem de trazer exatamente um relatório novo em relatorios/ (traz {len(reports)})")
    return out, reports


def report_problems(path, touched, read=lambda p: open(p, encoding="utf-8").read()):
    """O relatório tem de ser válido e dizer só o que o ramo traz (`touched`: caminhos A/M)."""
    try:
        rep = json.loads(read(path))
        relatorio.check(rep)
    except (OSError, ValueError) as e:
        return [f"{path}: relatório inválido ({e})"]
    return [f"{path}: o relatório diz que publicou {p['caminho']} mas o ramo não o traz"
            for p in rep["publicado"] if p["caminho"] not in touched]


def parse_raw(raw):
    """Lê a saída de `git diff --raw -z --no-renames` em (estado, caminho, modo)."""
    tokens = raw.split("\0")
    result, i = [], 0
    while i < len(tokens) and tokens[i]:
        meta = tokens[i].lstrip(":").split()
        if len(meta) < 5 or i + 1 >= len(tokens):
            raise ValueError("saída inesperada do git diff")
        old_mode, new_mode, status = meta[0], meta[1], meta[4]
        result.append((status, tokens[i + 1], old_mode if status.startswith("D") else new_mode))
        i += 2
    return result


def changes(base):
    r = subprocess.run(["git", "diff", "--raw", "-z", "--no-renames", f"{base}...HEAD"],
                       capture_output=True, text=True, check=True)
    return parse_raw(r.stdout)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--github-output")
    args = parser.parse_args(argv)
    try:
        diff = changes(args.base)
        found, reports = problems(diff)
    except (subprocess.CalledProcessError, ValueError, OSError) as e:
        detail = (getattr(e, "stderr", "") or str(e)).strip()
        print(f"não consegui comparar o ramo com {args.base}: {detail}")
        sys.exit(1)
    if len(reports) == 1:
        found += report_problems(reports[0], {c[1] for c in diff if c[0] in ("A", "M")})
    if subprocess.run(["git", "merge-base", "--is-ancestor", args.base, "HEAD"]).returncode != 0:
        found.append(f"o ramo não parte do {args.base} atual (não dá para juntar sem merge)")
    if found:
        print("\n".join(found))
        sys.exit(1)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"relatorio={reports[0]}\n")
    print(f"portão: ok ({reports[0]})")


if __name__ == "__main__":
    main()
