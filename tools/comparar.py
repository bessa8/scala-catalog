#!/usr/bin/env python3
"""Compara duas extrações do mesmo diploma, campo a campo.

    python3 tools/comparar.py A.json B.json

Ignora, no topo, «sources», «published» e «title» (dependem de quem extraiu).
Sai com 1 e lista as diferenças; com 0 imprime «iguais».
"""
import json
import sys
from pathlib import Path

IGNORE = {"sources", "published", "title"}


def diff(a, b, path="$"):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if path == "$" and k in IGNORE:
                continue
            if k not in a:
                out.append(f"{path}.{k}: só na segunda")
            elif k not in b:
                out.append(f"{path}.{k}: só na primeira")
            else:
                out += diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        out = [] if len(a) == len(b) else [f"{path}: {len(a)} elementos contra {len(b)}"]
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
        return out
    if type(a) is not type(b) or a != b:
        return [f"{path}: {json.dumps(a, ensure_ascii=False)} ≠ {json.dumps(b, ensure_ascii=False)}"]
    return []


def _no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"chave repetida: {k}")
        out[k] = v
    return out


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        sys.exit("uso: python3 tools/comparar.py A.json B.json")
    try:
        a, b = (load(p) for p in argv)
    except (ValueError, OSError) as e:
        print(f"não foi possível ler: {e}")
        sys.exit(1)
    problems = diff(a, b)
    if problems:
        print("\n".join(problems))
        sys.exit(1)
    print("iguais")


if __name__ == "__main__":
    main()
