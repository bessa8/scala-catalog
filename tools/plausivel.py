#!/usr/bin/env python3
"""Confere versões novas de tabelas contra a versão anterior da mesma tabela.

    python3 tools/plausivel.py --desde origin/main   # o que o ramo mudou em tables/ e tax/
    python3 tools/plausivel.py tables/tru.2027-01-01.json ...

Regras: nenhum valor muda mais de 15 %; nenhuma chave desaparece; a TRU cresce
de nível para nível; o salário mínimo e o IAS nunca descem; as tabelas de IRS
são as mesmas (I a VII). Caminhos em tools/aceites.json (aceites pelo Carlos)
não se conferem. Sai com 1 e lista os problemas.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"(tables|tax)/([a-z0-9-]+)\.(\d{4}-\d{2}-\d{2})\.json$")
LIMIT = 0.15


def _load(src, rel):
    return json.loads((Path(src) / rel).read_text(encoding="utf-8"))


def _change(a, b):
    if a == 0:
        return 0 if b == 0 else 1
    return abs(b - a) / abs(a)


def previous(src, rel):
    folder, tid, effective = NAME.match(rel).groups()
    older = []
    for p in (Path(src) / folder).glob(f"{tid}.*.json"):
        m = NAME.match(f"{folder}/{p.name}")
        if m and m[2] == tid and m[3] < effective:
            older.append(m[3])
    return f"{folder}/{tid}.{max(older)}.json" if older else None


def _tru(rel, new):
    out = []
    levels = sorted((int(k), v) for k, v in new["values"].items() if k.isdigit())
    for (l1, v1), (l2, v2) in zip(levels, levels[1:]):
        if v2 < v1:
            out.append(f"{rel}: o nível {l2} ({v2}) vale menos do que o nível {l1} ({v1})")
    return out


def check_pair(rel, prev, new):
    folder, tid, _ = NAME.match(rel).groups()
    out = []
    if folder == "tables":
        pv, nv = prev["values"], new["values"]
        for k, a in pv.items():
            if k not in nv:
                out.append(f"{rel}: «{k}» existia na versão anterior e desapareceu")
            elif _change(a, nv[k]) > LIMIT:
                out.append(f"{rel}: «{k}» muda {a} → {nv[k]} (mais de 15 %)")
            elif tid == "smn" and nv[k] < a:
                out.append(f"{rel}: «{k}» desce {a} → {nv[k]}")
    elif tid == "contributions":
        for k in ("ss", "cga", "health"):
            if _change(prev[k], new[k]) > LIMIT:
                out.append(f"{rel}: «{k}» muda {prev[k]} → {new[k]} (mais de 15 %)")
    elif tid == "youth":
        if new["ias"] < prev["ias"]:
            out.append(f"{rel}: o IAS desce {prev['ias']} → {new['ias']}")
        elif _change(prev["ias"], new["ias"]) > LIMIT:
            out.append(f"{rel}: o IAS muda {prev['ias']} → {new['ias']} (mais de 15 %)")
        if len(new["percent"]) != len(prev["percent"]):
            out.append(f"{rel}: «percent» tem {len(new['percent'])} anos e tinha {len(prev['percent'])}")
    elif tid.startswith("irs-"):
        if set(new["tables"]) != set(prev["tables"]):
            out.append(f"{rel}: as tabelas mudaram ({sorted(prev['tables'])} → {sorted(new['tables'])})")
    return out


def check(src, paths, accepted=()):
    out = []
    for rel in paths:
        m = NAME.match(rel)
        if not m or rel in accepted:
            continue
        new = _load(src, rel)
        if m[1] == "tables" and m[2] == "tru":
            out += _tru(rel, new)
        before = previous(src, rel)
        if before:
            out += check_pair(rel, _load(src, before), new)
    return out


def changed_since(ref, src):
    r = subprocess.run(["git", "diff", "--name-only", "--diff-filter=AM", f"{ref}...HEAD", "--", "tables", "tax"],
                       cwd=src, capture_output=True, text=True, check=True)
    return [line for line in r.stdout.splitlines() if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", type=Path, default=ROOT)
    parser.add_argument("--desde")
    parser.add_argument("caminhos", nargs="*")
    args = parser.parse_args(argv)
    paths = changed_since(args.desde, args.src) if args.desde else args.caminhos
    accepted_file = args.src / "tools" / "aceites.json"
    accepted = json.loads(accepted_file.read_text(encoding="utf-8")) if accepted_file.exists() else []
    problems = check(args.src, paths, accepted)
    if problems:
        print("\n".join(problems))
        sys.exit(1)
    print(f"plausível: {len(paths)} ficheiros")


if __name__ == "__main__":
    main()
