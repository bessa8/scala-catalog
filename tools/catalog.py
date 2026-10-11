#!/usr/bin/env python3
"""Valida e publica o catálogo da Scala (formato 2, um JSON por ficheiro).

    python3 tools/catalog.py validate              # confere o catálogo (a raiz deste repositório)
    python3 tools/catalog.py build                 # valida e escreve o manifest.json
    python3 tools/catalog.py build --src . --out DIR  # valida e copia para DIR (a app: assets/catalog)
    python3 tools/catalog.py list                  # o que há, com datas
    python3 tools/catalog.py verify DIR            # confere uma pasta publicada (manifest, sha256)
    python3 tools/catalog.py report [--out FILE]   # VERIFICAR.md: todos os valores e fontes

O formato está descrito no README.md.
"""
import argparse
import datetime
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT
OUT = ROOT
FORMAT = 2
FOLDERS = ("careers", "tables", "rules", "templates", "tax")
ROOT_FILES = ("professions.json", "institutions.json")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}$")
ID = re.compile(r"[a-z0-9][a-z0-9-]*$")
HOLIDAY = re.compile(r"((0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])|easter[+-]\d{1,3})$")
SECTORS = ("public", "private", "services")
PAY = ("monthly", "hourly", "hourlyFromMonthly")
# Como o relatório descreve cada modo de pagamento.
PAY_NAMES = {
    "monthly": "salário mensal",
    "hourly": "à hora",
    "hourlyFromMonthly": "à hora, tirado do mensal (só extra)",
}


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


class Invalid(Exception):
    pass


def need(condition, message):
    if not condition:
        raise Invalid(message)


def text(value, where):
    if isinstance(value, str):
        need(value.strip(), f"{where}: texto vazio")
        return
    need(
        isinstance(value, dict)
        and isinstance(value.get("pt"), str)
        and isinstance(value.get("en"), str)
        and value["pt"].strip()
        and value["en"].strip(),
        f"{where}: o texto tem de ter «pt» e «en»",
    )


def head(data, where):
    need(isinstance(data, dict), f"{where}: tem de ser um objeto")
    need(data.get("format") == FORMAT, f"{where}: «format» tem de ser {FORMAT}")
    need(
        isinstance(data.get("published"), str) and DATE.match(data["published"]),
        f"{where}: «published» tem de ser AAAA-MM-DD",
    )


def load(src):
    src = Path(src)
    paths = [src / name for name in ROOT_FILES if (src / name).exists()]
    for folder in FOLDERS:
        paths += (src / folder).rglob("*.json")
    files = {}
    for path in sorted(paths):
        rel = path.relative_to(src).as_posix()
        try:
            files[rel] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise Invalid(f"{rel}: JSON inválido ({e})")
    return files


def check_sources(rel, d):
    sources = d.get("sources", [])
    need(isinstance(sources, list), f"{rel}: «sources» tem de ser uma lista")
    for i, s in enumerate(sources, 1):
        w = f"{rel}: fonte {i}"
        need(isinstance(s, dict), f"{w}: tem de ser um objeto com «title», «url» e «consulted»")
        need(isinstance(s.get("title"), str) and s["title"].strip(), f"{w}: falta «title»")
        need(isinstance(s.get("url"), str) and s["url"].startswith("https://") and len(s["url"]) > len("https://"),
             f"{w}: «url» tem de começar por https://")
        consulted = s.get("consulted")
        ok = isinstance(consulted, str) and bool(DATE.match(consulted))
        if ok:
            try:
                datetime.date.fromisoformat(consulted)
            except ValueError:
                ok = False
        need(ok, f"{w}: «consulted» tem de ser uma data AAAA-MM-DD")


def check_table(rel, d):
    m = re.fullmatch(r"tables/([a-z0-9-]+)\.(\d{4}-\d{2}-\d{2})\.json", rel)
    need(m, f"{rel}: o nome tem de ser tables/<id>.<AAAA-MM-DD>.json")
    need(d.get("id") == m.group(1), f"{rel}: «id» tem de ser {m.group(1)}")
    need(d.get("effective") == m.group(2), f"{rel}: «effective» tem de ser {m.group(2)}")
    text(d.get("title"), f"{rel}: title")
    need(d.get("unit", "monthly") in ("monthly", "hourly"), f"{rel}: «unit» tem de ser monthly ou hourly")
    values = d.get("values")
    need(isinstance(values, dict) and values, f"{rel}: «values» vazio")
    for key, value in values.items():
        need(is_int(value) and value > 0, f"{rel}: o valor de «{key}» tem de ser inteiro positivo")
    check_sources(rel, d)


def table_keys(files):
    keys = {}
    for rel, d in files.items():
        if rel.startswith("tables/"):
            keys.setdefault(d["id"], []).append(set(d["values"]))
    return keys


def check_key(tables, table, key, where):
    need(table in tables, f"{where}: a tabela «{table}» não existe")
    need(all(key in ks for ks in tables[table]), f"{where}: a chave «{key}» falta numa versão da tabela {table}")


TAX_IDS = ("irs-continente", "irs-acores", "irs-madeira", "contributions", "youth")
IRS_TABLES = ("I", "II", "III", "IV", "V", "VI", "VII")
IRS_SITUATIONS = ("single", "married1", "married2")


def basis_points(value, where):
    need(is_int(value) and 0 <= value <= 10000, f"{where}: tem de ser inteiro entre 0 e 10000 (pontos-base)")


def irs_exact(line, r):
    """Retenção, em cêntimos, de [r] cêntimos numa linha, sem dependentes."""
    rate = line["rate"] / 10000
    formula = line.get("deductionFormula")
    deduction = rate * formula["factor"] * (formula["limit"] - r) if formula else line["deduction"]
    return max(0.0, r * rate - deduction)


def check_irs(rel, d):
    tables = d.get("tables")
    need(isinstance(tables, dict), f"{rel}: falta «tables»")
    for name in IRS_TABLES:
        need(name in tables, f"{rel}: falta a tabela {name}")
    for name, lines in tables.items():
        w = f"{rel}: tabela {name}"
        need(name in IRS_TABLES, f"{w}: nome desconhecido")
        need(isinstance(lines, list) and lines, f"{w}: sem linhas")
        previous = 0
        for i, line in enumerate(lines, 1):
            lw = f"{w}, linha {i}"
            need(isinstance(line, dict), f"{lw}: tem de ser um objeto")
            last = i == len(lines)
            if last:
                need(line.get("upTo") is None, f"{w}: a última linha não tem limite («upTo»: null)")
            else:
                need(is_int(line.get("upTo")) and line["upTo"] > previous, f"{lw}: «upTo» tem de subir por ordem crescente")
                previous = line["upTo"]
            basis_points(line.get("rate"), f"{lw}: «rate»")
            need(is_int(line.get("perDependent", 0)) and line.get("perDependent", 0) >= 0, f"{lw}: «perDependent» inválido")
            formula = line.get("deductionFormula")
            if formula is not None:
                need("deduction" not in line, f"{lw}: «deduction» ou «deductionFormula», não os dois")
                need(isinstance(formula, dict) and isinstance(formula.get("factor"), (int, float))
                     and not isinstance(formula.get("factor"), bool) and formula["factor"] > 0
                     and is_int(formula.get("limit")) and formula["limit"] > 0, f"{lw}: «deductionFormula» inválida")
            else:
                need(is_int(line.get("deduction")) and line["deduction"] >= 0, f"{lw}: «deduction» inválida")
            eff = line.get("effectiveAtLimit")
            if eff is not None:
                need(is_int(eff) and 0 <= eff <= 1000, f"{lw}: «effectiveAtLimit» inválido")
                need(not last, f"{lw}: a última linha não tem taxa efetiva")
                got = irs_exact(line, line["upTo"]) / line["upTo"] * 1000
                need(abs(got - eff) <= 0.51,
                     f"{lw}: a taxa efetiva no limite dá {got / 10:.2f} %, a publicada é {eff / 10:.1f} %")
    extras = d.get("extras")
    need(isinstance(extras, dict), f"{rel}: falta «extras»")
    dd = extras.get("disabledDependent")
    need(isinstance(dd, dict) and all(is_int(dd.get(s)) and dd[s] >= 0 for s in IRS_SITUATIONS),
         f"{rel}: «extras.disabledDependent» precisa de single, married1 e married2")
    for key in ("spouseDisabled", "threePlusCut", "overtimeShare"):
        need(is_int(extras.get(key)) and extras[key] >= 0, f"{rel}: «extras.{key}» inválido")


def check_tax(rel, d):
    m = re.fullmatch(r"tax/([a-z-]+)\.(\d{4}-\d{2}-\d{2})\.json", rel)
    need(m, f"{rel}: o nome tem de ser tax/<id>.<AAAA-MM-DD>.json")
    need(m.group(1) in TAX_IDS, f"{rel}: «{m.group(1)}» não é um id fiscal conhecido ({', '.join(TAX_IDS)})")
    need(d.get("id") == m.group(1), f"{rel}: «id» tem de ser {m.group(1)}")
    need(d.get("effective") == m.group(2), f"{rel}: «effective» tem de ser {m.group(2)}")
    text(d.get("title"), f"{rel}: title")
    check_sources(rel, d)
    need(d.get("sources"), f"{rel}: precisa de pelo menos uma fonte oficial")
    if m.group(1).startswith("irs-"):
        check_irs(rel, d)
    elif m.group(1) == "contributions":
        for key in ("ss", "cga", "health"):
            basis_points(d.get(key), f"{rel}: «{key}»")
    else:
        percent = d.get("percent")
        need(isinstance(percent, list) and len(percent) == 10, f"{rel}: «percent» tem de ter os 10 anos")
        need(all(is_int(p) and 0 <= p <= 100 for p in percent), f"{rel}: «percent» entre 0 e 100")
        need(is_int(d.get("ias")) and d["ias"] > 0, f"{rel}: «ias» inválido")


def check_career(rel, d, files, tables):
    need(rel == f"careers/{d.get('id')}.json", f"{rel}: «id» tem de coincidir com o nome do ficheiro")
    text(d.get("title"), f"{rel}: title")
    check_sources(rel, d)
    sectors = d.get("sectors")
    need(isinstance(sectors, dict) and sectors, f"{rel}: «sectors» vazio")
    for sid, s in sectors.items():
        w = f"{rel}: {sid}"
        need(sid in SECTORS, f"{w}: setor desconhecido")
        need(s.get("templates") in files and s["templates"].startswith("templates/"), f"{w}: «templates» não existe")
        if s.get("rules") is not None:
            need(s["rules"] in files and s["rules"].startswith("rules/"), f"{w}: «rules» não existe")
        need(isinstance(s.get("institutions", False), bool), f"{w}: «institutions» tem de ser true/false")
        deductions = s.get("deductions")
        if deductions is not None:
            need(isinstance(deductions, dict)
                 and deductions.get("social", "ss") in ("ss", "cga", "none")
                 and isinstance(deductions.get("health", False), bool)
                 and set(deductions) <= {"social", "health"},
                 f"{w}: «deductions» inválido")
        categories = s.get("categories")
        need(isinstance(categories, list) and categories, f"{w}: sem categorias")
        for c in categories:
            cw = f"{w}/{c.get('id')}"
            need(isinstance(c.get("id"), str) and ID.match(c["id"]), f"{cw}: «id» inválido")
            text(c.get("title"), f"{cw}: title")
            regimes = c.get("regimes")
            need(isinstance(regimes, list) and regimes, f"{cw}: sem regimes")
            for r in regimes:
                rw = f"{cw}/{r.get('id')}"
                need(isinstance(r.get("id"), str) and ID.match(r["id"]), f"{rw}: «id» inválido")
                text(r.get("title"), f"{rw}: title")
                weekly = r.get("weeklyHours")
                need(isinstance(weekly, (int, float)) and 0 <= weekly <= 168, f"{rw}: «weeklyHours» inválido")
                pay = r.get("pay", "monthly")
                need(pay in PAY, f"{rw}: «pay» tem de ser um de {', '.join(PAY)}")
                calc = r.get("calculationHours", weekly)
                need(isinstance(calc, (int, float)) and calc >= 0, f"{rw}: «calculationHours» inválido")
                if pay in ("hourly", "hourlyFromMonthly"):
                    need(calc > 0, f"{rw}: «calculationHours» tem de ser maior que 0")
                for key in ("templates", "rules"):
                    if r.get(key) is not None:
                        need(r[key] in files, f"{rw}: «{key}» não existe")
                for p in r.get("positions", []):
                    pw = f"{rw}/{p.get('id')}"
                    need(isinstance(p.get("id"), str) and p["id"], f"{pw}: «id» em falta")
                    text(p.get("label"), f"{pw}: label")
                    check_key(tables, p.get("table"), p.get("key"), pw)
        for q in s.get("questions", []):
            qw = f"{w}/pergunta {q.get('id')}"
            need(isinstance(q.get("id"), str) and ID.match(q["id"]), f"{qw}: «id» inválido")
            text(q.get("label"), f"{qw}: label")
            if q.get("unit") is not None:
                text(q["unit"], f"{qw}: unit")
            effect = (q.get("effect") or {}).get("monthlySupplement")
            need(isinstance(effect, dict), f"{qw}: falta «effect.monthlySupplement»")
            kinds = [k for k in ("perUnitCents", "table", "brackets") if k in effect]
            need(len(kinds) == 1, f"{qw}: usa um e só um de perUnitCents, table ou brackets")
            if "perUnitCents" in effect:
                need(is_int(effect["perUnitCents"]), f"{qw}: «perUnitCents» tem de ser inteiro")
            if "table" in effect:
                check_key(tables, effect["table"], effect.get("key"), qw)
            if "brackets" in effect:
                brackets = effect["brackets"]
                need(
                    isinstance(brackets, list) and brackets
                    and all(isinstance(b.get("from"), (int, float)) and is_int(b.get("cents")) for b in brackets),
                    f"{qw}: escalões inválidos",
                )
        template_paths = {r.get("templates") or s["templates"] for c in categories for r in c.get("regimes", [])}
        allowed = None
        for tp in template_paths:
            ids = {t.get("id") for t in files.get(tp, {}).get("job", {}).get("templates", [])}
            allowed = ids if allowed is None else allowed & ids
        allowed = (allowed or set()) | {"F", "D"}
        for rot in s.get("rotations", []):
            ow = f"{w}/rotação {rot.get('id')}"
            need(isinstance(rot.get("id"), str) and ID.match(rot["id"]), f"{ow}: «id» inválido")
            text(rot.get("title"), f"{ow}: title")
            codes = rot.get("codes")
            need(isinstance(codes, list) and codes and all(isinstance(x, str) and x for x in codes), f"{ow}: «codes» vazio")
            for x in codes:
                need(x in allowed, f"{ow}: código «{x}» não é um modelo de turno do setor, nem F ou D")


def check_professions(d, files):
    areas = d.get("areas")
    need(isinstance(areas, list) and areas, "professions.json: sem áreas")
    for a in areas:
        aw = f"professions.json: {a.get('id')}"
        need(isinstance(a.get("id"), str) and ID.match(a["id"]), f"{aw}: «id» inválido")
        text(a.get("title"), f"{aw}: title")
        for p in a.get("professions", []):
            pw = f"{aw}/{p.get('id')}"
            need(isinstance(p.get("id"), str) and ID.match(p["id"]), f"{pw}: «id» inválido")
            text(p.get("title"), f"{pw}: title")
            if p.get("subtitle") is not None:
                text(p["subtitle"], f"{pw}: subtitle")
            need(isinstance(p.get("search", ""), str), f"{pw}: «search» tem de ser texto")
            need(isinstance(p.get("career"), str) and p["career"].startswith("careers/") and p["career"] in files, f"{pw}: a carreira «{p.get('career')}» tem de existir em careers/")


def check_institutions(d):
    items = d.get("institutions")
    need(isinstance(items, list), "institutions.json: «institutions» tem de ser uma lista")
    check_sources("institutions.json", d)
    need(all(isinstance(i, dict) for i in items), "institutions.json: cada instituição tem de ser um objeto")
    ids = [i.get("id") for i in items]
    need(len(ids) == len(set(ids)), "institutions.json: há ids repetidos")
    for i in items:
        iw = f"institutions.json: {i.get('id')}"
        need(isinstance(i.get("id"), str) and ID.match(i["id"]), f"{iw}: «id» inválido")
        for key in ("name", "short", "municipality"):
            need(isinstance(i.get(key), str) and i[key].strip(), f"{iw}: falta «{key}»")
        need(isinstance(i.get("holiday"), str) and HOLIDAY.match(i["holiday"]), f"{iw}: «holiday» tem de ser MM-DD ou easter+N")
        text(i.get("holidayName"), f"{iw}: holidayName")


def validate(src=SRC):
    files = load(src)
    for name in ROOT_FILES:
        need(name in files, f"falta {name}")
    for rel, d in files.items():
        head(d, rel)
        top = rel.split("/")[0]
        need(rel in ROOT_FILES or top in FOLDERS, f"{rel}: pasta desconhecida")
    for rel, d in files.items():
        if rel.startswith("tables/"):
            check_table(rel, d)
        elif rel.startswith("templates/"):
            need(isinstance(d.get("job"), dict) and isinstance(d["job"].get("templates", []), list), f"{rel}: falta «job»")
            need("profiles" not in d["job"], f"{rel}: «job» não pode ter «profiles»")
            pay = d.get("pay", {})
            need(isinstance(pay, dict), f"{rel}: «pay» tem de ser um objeto")
            for key in ("supplementDelay", "extraDelay", "extraFirst", "extraLater"):
                if key in pay:
                    need(is_int(pay[key]), f"{rel}: «{key}» tem de ser inteiro")
            if "calculationHours" in pay:
                need(isinstance(pay["calculationHours"], (int, float)) and not isinstance(pay["calculationHours"], bool) and pay["calculationHours"] > 0, f"{rel}: «calculationHours» inválido")
        elif rel.startswith("tax/"):
            check_tax(rel, d)
        elif rel.startswith("rules/"):
            text(d.get("title"), f"{rel}: title")
            if d.get("subtitle") is not None:
                text(d["subtitle"], f"{rel}: subtitle")
            need(isinstance(d.get("rules"), list) and d["rules"], f"{rel}: «rules» vazio")
    tables = table_keys(files)
    for rel, d in files.items():
        if rel.startswith("careers/"):
            check_career(rel, d, files, tables)
    check_professions(files["professions.json"], files)
    check_institutions(files["institutions.json"])
    return files


def build(src=SRC, out=OUT):
    files = validate(src)
    src, out = Path(src), Path(out)
    in_place = src.resolve() == out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not in_place:
        for folder in FOLDERS:
            shutil.rmtree(out / folder, ignore_errors=True)
        for name in ROOT_FILES + ("manifest.json",):
            (out / name).unlink(missing_ok=True)
    entries = []
    for rel, d in sorted(files.items()):
        data = (src / rel).read_bytes()
        if not in_place:
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        entries.append({
            "path": rel,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "format": d["format"],
            "published": d["published"],
        })
    manifest = {
        "format": FORMAT,
        "published": max(e["published"] for e in entries),
        "movedTo": None,
        "files": entries,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify(root):
    root = Path(root)
    files = validate(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    listed = {e["path"]: e for e in manifest.get("files", [])}
    for rel in files:
        need(rel in listed, f"{rel}: não está no manifest")
    for rel, entry in listed.items():
        path = root / rel
        need(path.exists(), f"{rel}: está no manifest mas não existe")
        data = path.read_bytes()
        need(hashlib.sha256(data).hexdigest() == entry.get("sha256"), f"{rel}: sha256 não confere")
        need(len(data) == entry.get("bytes"), f"{rel}: bytes não conferem")
    return manifest


def label(value):
    return value if isinstance(value, str) else value.get("pt", "")


def euros(cents):
    whole, frac = divmod(abs(cents), 100)
    return f"{'-' if cents < 0 else ''}{whole:,}".replace(",", " ") + f",{frac:02d} €"


def euros_per_hour(micros):
    whole, frac = divmod(abs(micros), 10_000_000)
    decimals = f"{frac:07d}".rstrip("0").ljust(2, "0")
    return f"{'-' if micros < 0 else ''}{whole:,}".replace(",", " ") + f",{decimals} €/h"


def number(value):
    return str(int(value)) if float(value).is_integer() else str(value)


def table_ref(table, key):
    return f"tabela `{table}`, chave `{key}`"


def money(unit, value):
    return euros_per_hour(value) if unit == "hourly" else euros(value)


def source_lines(d):
    return [f"  - {s['title']} — {s['url']} (consultado em {s['consulted']})" for s in d.get("sources", [])]


def pct(basis_points):
    return f"{basis_points / 100:.2f}".replace(".", ",") + " %"


def irs_deduction(line):
    formula = line.get("deductionFormula")
    if formula:
        return f"taxa × {str(formula['factor']).replace('.', ',')} × ({euros(formula['limit'])} − R)"
    return euros(line["deduction"])


def tax_report(files):
    """A secção «Tabelas fiscais» do relatório: cada ficheiro de `tax/`, linha a linha."""
    tax = sorted((d for rel, d in files.items() if rel.startswith("tax/")), key=lambda d: (d["id"], d["effective"]))
    if not tax:
        return []
    out = ["## Tabelas fiscais", "",
           "R é o rendimento mensal sujeito a retenção. Valores em cêntimos no catálogo, aqui em euros; taxas em %.", ""]
    for d in tax:
        out += [f"### {label(d['title'])} (`{d['id']}`) — vigência {d['effective']}, publicada {d['published']}", ""]
        if d["id"].startswith("irs-"):
            for name, lines in d["tables"].items():
                out += [f"#### Tabela {name}", ""]
                previous = None
                for line in lines:
                    limit = f"até {euros(line['upTo'])}" if line.get("upTo") is not None else f"acima de {euros(previous)}"
                    parts = [f"taxa {pct(line['rate'])}", f"parcela a abater {irs_deduction(line)}",
                             f"por dependente {euros(line.get('perDependent', 0))}"]
                    if line.get("effectiveAtLimit") is not None:
                        parts.append(f"taxa efetiva no limite {line['effectiveAtLimit'] / 10:.1f}".replace(".", ",") + " %")
                    out.append(f"- {limit}: " + ", ".join(parts))
                    previous = line.get("upTo")
                out.append("")
            e = d["extras"]
            dd = e["disabledDependent"]
            out += ["#### Extras", "",
                    f"- dependente com deficiência: {euros(dd['single'])} (solteiro), {euros(dd['married1'])} "
                    f"(casado, um titular), {euros(dd['married2'])} (casado, dois titulares)",
                    f"- cônjuge com deficiência: {euros(e['spouseDisabled'])}",
                    f"- três ou mais dependentes: retirar {e['threePlusCut'] / 100:.2f} pp à taxa".replace(".", ",", 1),
                    f"- extras (retenção sobre o valor): {e['overtimeShare']} % da taxa efetiva", ""]
        elif d["id"] == "contributions":
            out += [f"- Segurança Social {pct(d['ss'])}, CGA {pct(d['cga'])}, saúde {pct(d['health'])}", ""]
        else:
            out += ["- isenção por ano: " + ", ".join(f"{p} %" for p in d["percent"]),
                    f"- IAS {euros(d['ias'])}", ""]
        sources = source_lines(d)
        out += ["Fontes:" if sources else "Fontes: nenhuma."] + sources + [""]
    return out


def report(src=SRC):
    """Markdown com todos os valores e fontes do catálogo, para ler valor a valor antes de publicar."""
    files = validate(src)
    versions = {}
    for rel, d in files.items():
        if rel.startswith("tables/"):
            versions.setdefault(d["id"], []).append(d)
    for ds in versions.values():
        ds.sort(key=lambda d: d["effective"])

    def latest(table, key):
        d = versions[table][-1]
        return money(d.get("unit", "monthly"), d["values"][key])

    out = ["# Verificar catálogo", "",
           "Gerado por `python3 tools/catalog.py report`. Ler valor a valor antes de publicar.", "",
           "## Tabelas", ""]
    for tid in sorted(versions):
        for d in versions[tid]:
            unit = d.get("unit", "monthly")
            out += [f"### {label(d['title'])} (`{tid}`) — vigência {d['effective']}, publicada {d['published']}", ""]
            out += [f"- `{key}`: {money(unit, value)}" for key, value in d["values"].items()]
            sources = source_lines(d)
            out += ["", "Fontes:" if sources else "Fontes: nenhuma."] + sources + [""]
    out += ["## Carreiras", ""]
    without = []
    sector_names = {"public": "Público", "private": "Privado", "services": "Serviços"}
    for rel, d in sorted(files.items()):
        if not rel.startswith("careers/"):
            continue
        out += [f"### {label(d['title'])} (`{d['id']}`)", ""]
        for sid, s in d["sectors"].items():
            out += [f"#### Setor {sector_names.get(sid, sid)}", ""]
            for c in s["categories"]:
                for r in c["regimes"]:
                    head_line = f"- {label(c['title'])} / {label(r['title'])} ({number(r['weeklyHours'])} h/semana, {PAY_NAMES.get(r.get('pay', 'monthly'), r.get('pay'))})"
                    positions = r.get("positions", [])
                    if not positions:
                        without.append(f"{label(d['title'])} / {sector_names.get(sid, sid)} / {label(c['title'])} / {label(r['title'])}")
                        out.append(head_line + ": sem posições")
                        continue
                    out.append(head_line)
                    for p in positions:
                        out.append(f"  - {label(p['label'])} — {table_ref(p['table'], p['key'])}: {latest(p['table'], p['key'])}")
            for q in s.get("questions", []):
                e = q["effect"]["monthlySupplement"]
                if "perUnitCents" in e:
                    effect = f"{euros(e['perUnitCents'])} por unidade"
                elif "table" in e:
                    effect = f"{table_ref(e['table'], e['key'])}: {latest(e['table'], e['key'])}"
                else:
                    effect = ", ".join(f"a partir de {b['from']}: {euros(b['cents'])}" for b in e["brackets"])
                out.append(f"- Pergunta «{label(q['label'])}»: suplemento mensal {effect}")
            for rot in s.get("rotations", []):
                out.append(f"- Rotação «{label(rot['title'])}»: {' '.join(rot['codes'])}")
            out.append("")
        sources = source_lines(d)
        out += ["Fontes da carreira:" if sources else "Fontes da carreira: nenhuma."] + sources + [""]
    institutions = files["institutions.json"]
    out += ["## Instituições", "",
            "Cada instituição leva o feriado municipal do concelho da sede (`MM-DD` ou `easter±N`).", ""]
    for i in institutions["institutions"]:
        out.append(f"- `{i['id']}`: {i['name']} — {i['municipality']}, `{i['holiday']}` ({label(i['holidayName'])})")
    sources = source_lines(institutions)
    out += ["", "Fontes das instituições:" if sources else "Fontes das instituições: nenhuma."] + sources + [""]
    out += tax_report(files)
    out += ["## Sem tabela", ""]
    out += [f"- {w}" for w in without] if without else ["Nenhum."]
    out += ["", "## Por confirmar", ""]
    pending = Path(src) / "por-confirmar.md"
    content = pending.read_text(encoding="utf-8").strip() if pending.exists() else ""
    out.append(content if content else "Nada por confirmar.")
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="confere o catálogo")
    v.add_argument("--src", default=SRC)
    b = sub.add_parser("build", help="valida e escreve o manifest.json (ou copia para --out)")
    b.add_argument("--src", default=SRC)
    b.add_argument("--out", default=OUT)
    l = sub.add_parser("list", help="lista os ficheiros do catálogo")
    l.add_argument("--src", default=SRC)
    vf = sub.add_parser("verify", help="confere uma pasta publicada (manifest e ficheiros)")
    vf.add_argument("dir")
    rp = sub.add_parser("report", help="escreve o relatório de verificação (valores, fontes, por confirmar)")
    rp.add_argument("--src", default=SRC)
    rp.add_argument("--out", default=ROOT / "VERIFICAR.md")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            files = validate(args.src)
            print(f"válido: {len(files)} ficheiros")
        elif args.command == "build":
            manifest = build(args.src, args.out)
            print(f"{len(manifest['files'])} ficheiros em {args.out}")
        elif args.command == "verify":
            manifest = verify(args.dir)
            print(f"verificado: {len(manifest['files'])} ficheiros")
        elif args.command == "report":
            Path(args.out).write_text(report(args.src), encoding="utf-8")
            print(f"relatório em {args.out}")
        else:
            for rel, d in sorted(load(args.src).items()):
                print(f"{d.get('published', '?')}  {rel}")
    except Invalid as e:
        sys.exit(f"erro: {e}")


if __name__ == "__main__":
    main()
