#!/usr/bin/env python3
"""Vigia das fontes oficiais do catálogo, sem IA.

    python3 tools/vigia.py diario [--issues FICHEIRO]   # lê as fontes e junta as pistas ao estado
    python3 tools/vigia.py semanal [--issues FICHEIRO]  # com pistas, prepara a issue «Novidades da semana»

As fontes e os temas estão em tools/vigia.json; o que já se viu, em
tools/estado.json. As issues a abrir ficam em FICHEIRO (lista JSON) para
tools/issues.py as abrir.
"""
import argparse
import datetime
import html
import json
import re
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "tools" / "vigia.json"
STATE = ROOT / "tools" / "estado.json"
USER_AGENT = "Mozilla/5.0 (compatible; scala-catalog-vigia; +https://github.com/bessa8/scala-catalog)"
KEEP_DAYS = 60       # quanto tempo um link do RSS fica registado como visto
FAILS_FOR_ISSUE = 3  # dias seguidos sem abrir até haver uma issue
LOOKAHEAD = 3        # números de circular espreitados à frente (há buracos)


def normalize(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().split())


def themes_for(text, temas):
    t = normalize(text)
    return [tema["id"] for tema in temas if any(normalize(p) in t for p in tema["palavras"])]


def rss_items(xml_text):
    root = ET.fromstring(xml_text)
    if root.tag != "rss":
        raise ValueError("não é um RSS")
    items = []
    for item in root.iter("item"):
        fields = {}
        for tag in ("title", "description", "link"):
            e = item.find(tag)
            fields[tag] = " ".join((e.text or "").split()) if e is not None else ""
        items.append({"titulo": fields["title"], "resumo": html.unescape(fields["description"]), "link": fields["link"]})
    return items


def links(html_text, padrao):
    return sorted(set(re.findall(padrao, html_text)))


def empty_state():
    return {"ultimaVerificacao": None, "fontes": {}, "pistas": [], "falhas": {}}


def _rss(f, mem, temas, fetch, today):
    seen = mem.setdefault("vistos", {})
    cutoff = (today - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    for link in [link for link, day in seen.items() if day < cutoff]:
        del seen[link]
    leads = []
    for item in rss_items(fetch(f["url"])):
        if not item["link"] or item["link"] in seen:
            continue
        seen[item["link"]] = today.isoformat()
        temas_item = themes_for(f"{item['titulo']} {item['resumo']}", temas)
        if temas_item:
            leads.append({"temas": temas_item, **item})
    return leads


def _links(f, mem, fetch):
    found = links(fetch(f["url"]), f["padrao"])
    if not found:
        raise ValueError("nenhum documento na página")
    before = mem.get("lista")
    mem["lista"] = found
    if before is None:
        return []
    return [{"temas": [f["tema"]], "titulo": f"Documento novo: {name}", "resumo": "", "link": f["url"]}
            for name in found if name not in before]


def _circulars(f, mem, exists, today):
    first = "ultimas" not in mem
    last = mem.setdefault("ultimas", {})
    years = [today.year] + ([today.year + 1] if today.month == 12 else [])
    leads = []
    for year in years:
        n = last.get(str(year), 0)
        while True:
            hit = None
            for ahead in range(1, LOOKAHEAD + 1):
                for name in f["nomes"]:
                    url = f["url"] + name.format(n=n + ahead, ano=year)
                    if exists(url):
                        hit = (n + ahead, url)
                        break
                if hit:
                    break
            if hit is None:
                break
            n = hit[0]
            if not first:
                leads.append({"temas": [f["tema"]], "titulo": f"Circular n.º {n}/{year} da AT", "resumo": "", "link": hit[1]})
        last[str(year)] = n
    return leads


def daily(state, config, fetch, exists, now):
    today = now.date()
    issues = []
    for fid, f in config["fontes"].items():
        mem = state["fontes"].setdefault(fid, {})
        try:
            if f["tipo"] == "rss":
                leads = _rss(f, mem, config["temas"], fetch, today)
            elif f["tipo"] == "links":
                leads = _links(f, mem, fetch)
            elif f["tipo"] == "circulares":
                leads = _circulars(f, mem, exists, today)
            else:
                raise ValueError(f"tipo desconhecido: {f['tipo']}")
        except Exception as e:  # uma fonte que falha não pára as outras
            fails = state["falhas"].setdefault(fid, [])
            if today.isoformat() not in fails:
                fails.append(today.isoformat())
            if len(fails) == FAILS_FOR_ISSUE:
                issues.append({
                    "tipo": "criar",
                    "titulo": f"Fonte inacessível: {fid}",
                    "corpo": f"A vigia não consegue ler {f['url']} desde {fails[0]} ({type(e).__name__}: {e}).\n\n"
                             "Corrigir o endereço em `tools/vigia.json`. Esta issue não volta a abrir até a fonte responder.",
                    "etiquetas": ["fonte"],
                    "fechar": False,
                })
            continue
        state["falhas"].pop(fid, None)
        for lead in leads:
            state["pistas"].append({**lead, "fonte": fid, "vistaEm": today.isoformat()})
    state["ultimaVerificacao"] = now.isoformat(timespec="minutes")
    return state, issues


def weekly(state, now):
    leads = state["pistas"]
    if not leads:
        return None
    state["pistas"] = []
    lines = []
    for p in leads:
        lines.append(f"- **[{', '.join(p['temas'])}]** {p['titulo']} — {p['link']} (fonte: {p['fonte']}, vista em {p['vistaEm']})")
        if p["resumo"]:
            lines.append(f"  {p['resumo']}")
    corpo = ("A vigia encontrou isto nas fontes oficiais. A rotina segue o `ROTINA.md`.\n\n"
             + "\n".join(lines)
             + "\n\n```json\n" + json.dumps(leads, ensure_ascii=False, indent=2) + "\n```\n")
    return {"tipo": "criar", "titulo": f"Novidades da semana ({now.date().isoformat()})",
            "corpo": corpo, "etiquetas": ["novidade"], "fechar": False}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def exists(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def load_state(path):
    path = Path(path)
    if not path.exists():
        return empty_state()
    return {**empty_state(), **json.loads(path.read_text(encoding="utf-8"))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("modo", choices=("diario", "semanal"))
    parser.add_argument("--issues", type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--estado", type=Path, default=STATE)
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    state = load_state(args.estado)
    now = datetime.datetime.now(datetime.timezone.utc)
    if args.modo == "diario":
        state, issues = daily(state, config, fetch, exists, now)
    else:
        issue = weekly(state, now)
        issues = [issue] if issue else []
    args.estado.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.issues is not None:
        args.issues.write_text(json.dumps(issues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{args.modo}: {len(state['pistas'])} pistas por entregar, {len(issues)} issues")


if __name__ == "__main__":
    main()
