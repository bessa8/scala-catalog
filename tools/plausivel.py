#!/usr/bin/env python3
"""Confere versões novas de tabelas contra a versão anterior da mesma tabela.

    python3 tools/plausivel.py --desde origin/main   # o que o ramo mudou em tables/ e tax/
    python3 tools/plausivel.py tables/tru.2027-01-01.json ...
    python3 tools/plausivel.py --hash tables/tru.2027-01-01.json   # hash dos dados, para aceites.json

Regras: nenhum valor muda mais de 15 %; nenhuma chave desaparece; a TRU cresce
de nível para nível; o salário mínimo e o IAS nunca descem; as tabelas de IRS
são as mesmas (I a VII); nenhuma chave nova nem unidade diferente (a rotina não
cria estrutura); nada fora do padrão <pasta>/<id>.<AAAA-MM-DD>.json. Com --desde,
os ficheiros que já existiam em REF (retificações) também se conferem contra o
conteúdo antigo. tools/aceites.json é uma lista de {"caminho", "sha256"} aceites
pelo Carlos: um ficheiro só se salta enquanto o hash dos seus dados (tudo menos
published, sources e title) for esse; `--hash CAMINHO` imprime esse hash. Falha
fechado: qualquer erro ao ler ou conferir um ficheiro é um problema. Sai com 1
e lista os problemas.
"""
import argparse
import hashlib
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


def _shape(rel, new):
    """Em tables/, «values» é um dicionário de inteiros (não booleanos)."""
    values = new["values"]
    if not isinstance(values, dict):
        return [f"{rel}: «values» não é um dicionário"]
    return [f"{rel}: «{k}» não é um inteiro ({json.dumps(v)})"
            for k, v in values.items() if type(v) is not int]


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
        for k in nv:
            if k not in pv:
                out.append(f"{rel}: «{k}» é nova (a rotina não cria estrutura)")
        if prev.get("unit") != new.get("unit"):
            out.append(f"{rel}: «unit» muda {prev.get('unit')} → {new.get('unit')}")
    elif tid == "contributions":
        for k in ("ss", "cga", "health"):
            if _change(prev[k], new[k]) > LIMIT:
                out.append(f"{rel}: «{k}» muda {prev[k]} → {new[k]} (mais de 15 %)")
    elif tid == "youth":
        if new["ias"] < prev["ias"]:
            out.append(f"{rel}: o IAS desce {prev['ias']} → {new['ias']}")
        elif _change(prev["ias"], new["ias"]) > LIMIT:
            out.append(f"{rel}: o IAS muda {prev['ias']} → {new['ias']} (mais de 15 %)")
        if new["percent"] != prev["percent"]:
            out.append(f"{rel}: «percent» muda {prev['percent']} → {new['percent']}")
    elif tid.startswith("irs-"):
        if set(new["tables"]) != set(prev["tables"]):
            out.append(f"{rel}: as tabelas mudaram ({sorted(prev['tables'])} → {sorted(new['tables'])})")
        pe, ne = set(prev.get("extras", {})), set(new.get("extras", {}))
        if pe != ne:
            out.append(f"{rel}: os «extras» mudaram ({sorted(pe)} → {sorted(ne)})")
    return out


def _known_tax(tid):
    return tid in ("contributions", "youth") or tid.startswith("irs-")


def _git(src, *args):
    r = subprocess.run(["git", *args], cwd=src, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip() or r.returncode}")
    return r.stdout


def _old_content(src, desde, rel):
    """Conteúdo do ficheiro em «desde», ou None se ainda não existia lá."""
    if not _git(src, "ls-tree", desde, "--", rel).strip():
        return None
    return json.loads(_git(src, "show", f"{desde}:{rel}"))


def _check_file(src, rel, m, desde):
    out = []
    new = _load(src, rel)
    if m[1] == "tax" and not _known_tax(m[2]):
        return [f"{rel}: id de tabela fiscal desconhecido"]
    if m[1] == "tables":
        out += _shape(rel, new)
        if out:
            return out
        if m[2] == "tru":
            out += _tru(rel, new)
    refs = []
    before = previous(src, rel)
    if before:
        refs.append(_load(src, before))
    if desde:
        old = _old_content(src, desde, rel)
        if old is not None:
            refs.append(old)
    for prev in refs:
        out += check_pair(rel, prev, new)
    return list(dict.fromkeys(out))


def _normalize(rel):
    rel = str(rel)
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


NOT_DATA = ("published", "sources", "title")


def sha256(src, rel):
    """Hash dos DADOS do ficheiro (sem published, sources nem title; chaves ordenadas), não dos bytes."""
    data = _load(src, rel)
    if not isinstance(data, dict):
        raise ValueError("o ficheiro não é um objeto JSON")
    canonical = json.dumps({k: v for k, v in data.items() if k not in NOT_DATA},
                           sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def accepted_map(accepted):
    """{caminho: sha256}; levanta ValueError se uma entrada não tiver o formato certo."""
    out = {}
    for entry in accepted:
        if (not isinstance(entry, dict) or not isinstance(entry.get("caminho"), str)
                or not isinstance(entry.get("sha256"), str)):
            raise ValueError(f"entrada inválida em aceites.json (esperado {{\"caminho\", \"sha256\"}}): {entry!r}")
        out[_normalize(entry["caminho"])] = entry["sha256"]
    return out


def check_counted(src, paths, accepted=(), desde=None):
    """Devolve (problemas, ficheiros conferidos, ficheiros aceites e saltados)."""
    out, checked, skipped = [], 0, 0
    ok = accepted_map(accepted)
    for raw in paths:
        rel = _normalize(raw)
        m = NAME.match(rel)
        if not m:
            out.append(f"{rel}: ficheiro fora do padrão <pasta>/<id>.<AAAA-MM-DD>.json")
            continue
        try:
            if rel in ok and sha256(src, rel) == ok[rel]:
                skipped += 1
                continue
            problems = _check_file(src, rel, m, desde)
        except Exception as e:  # falha fechado: nada de tracebacks nem de saltos silenciosos
            problems = [f"{rel}: não foi possível conferir ({type(e).__name__}: {e})"]
        checked += 1
        out += problems
    return out, checked, skipped


def check(src, paths, accepted=(), desde=None):
    return check_counted(src, paths, accepted, desde)[0]


def changed_since(ref, src):
    """(base, caminhos): ficheiros de tables/ e tax/ acrescentados ou alterados desde REF."""
    base = _git(src, "merge-base", ref, "HEAD").strip()
    names = _git(src, "diff", "--name-only", "--no-renames", "--diff-filter=AM", f"{base}...HEAD", "--", "tables", "tax")
    return base, [line for line in names.splitlines() if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", type=Path, default=ROOT)
    parser.add_argument("--desde")
    parser.add_argument("--hash", metavar="CAMINHO", help="imprime o hash dos dados do ficheiro e sai")
    parser.add_argument("caminhos", nargs="*")
    args = parser.parse_args(argv)
    if args.hash:
        try:
            print(sha256(args.src, _normalize(args.hash)))
        except (ValueError, OSError) as e:
            print(f"não foi possível calcular o hash ({type(e).__name__}: {e})")
            sys.exit(1)
        return
    try:
        base = None
        paths = args.caminhos
        if args.desde:
            base, paths = changed_since(args.desde, args.src)
        accepted_file = args.src / "tools" / "aceites.json"
        accepted = json.loads(accepted_file.read_text(encoding="utf-8")) if accepted_file.exists() else []
        problems, checked, skipped = check_counted(args.src, paths, accepted, base)
    except (RuntimeError, ValueError, OSError) as e:
        print(f"não foi possível conferir ({type(e).__name__}: {e})")
        sys.exit(1)
    if problems:
        print("\n".join(problems))
        sys.exit(1)
    print(f"plausível: {checked} ficheiros conferidos" + (f", {skipped} aceites" if skipped else ""))


if __name__ == "__main__":
    main()
