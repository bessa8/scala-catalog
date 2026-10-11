#!/usr/bin/env python3
"""Vigia das fontes oficiais do catálogo, sem IA.

    python3 tools/vigia.py diario [--issues FICHEIRO]   # lê as fontes e junta as pistas ao estado
    python3 tools/vigia.py semanal [--issues FICHEIRO] [--abertas FICHEIRO]
        # com pistas, prepara a issue «Novidades da semana»; com --abertas, avisa das issues que a rotina não tratou

--abertas é a lista JSON das issues abertas, de uma só chamada (o `gh` junta com «E» as etiquetas repetidas,
por isso não se filtra por etiqueta; a vigia filtra novidade/rever):
    gh issue list --state open --limit 200 --json number,title,createdAt,updatedAt,labels > abertas.json

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
import urllib.parse
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
MAX_CIRCULARS_PER_RUN = 20   # circulares novas por ano e por corrida (trava contra respostas «sempre sim»)
MAX_CIRCULARS_FIRST_RUN = 200  # na primeira corrida só se regista o ponto de partida, com folga
MAX_BODY_CHARS = 60000       # o GitHub aceita 65536 caracteres no corpo de uma issue
STALE_DAYS = 2               # uma issue novidade/rever aberta há mais de tanto tempo é um aviso: a rotina não a tratou
WATCHED_LABELS = ("novidade", "rever")
IGNORED_LINK_PARTS = ("/aviso/", "/aviso-extrato/")  # avisos de recrutamento e mobilidade: nunca mexem no catálogo


def normalize(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().split())


def themes_for(text, temas):
    t = normalize(text)
    return [tema["id"] for tema in temas if any(normalize(p) in t for p in tema["palavras"])]


def ignored_link(link):
    path = urllib.parse.urlparse(link).path
    return any(part in path for part in IGNORED_LINK_PARTS)


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
    items = rss_items(fetch(f["url"]))
    if not items:  # um feed que lê mas vem vazio está avariado (o DR publica todos os dias)
        raise ValueError("o feed não traz nenhum item")
    for item in items:
        if not item["link"] or item["link"] in seen or ignored_link(item["link"]):
            continue
        temas_item = themes_for(f"{item['titulo']} {item['resumo']}", temas)
        if temas_item:  # só as pistas ficam registadas: o resto não gera nada, não precisa de deduplicação
            seen[item["link"]] = today.isoformat()
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
    first = not mem.get("ultimas")
    cap = MAX_CIRCULARS_FIRST_RUN if first else MAX_CIRCULARS_PER_RUN
    previous = mem.get("ultimas", {})
    new_last = {}
    years = [today.year] + ([today.year + 1] if today.month == 12 else [])
    leads = []
    for year in years:
        n = previous.get(str(year), 0)
        found = 0
        while found < cap:
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
            found += 1
            if not first:
                leads.append({"temas": [f["tema"]], "titulo": f"Circular n.º {n}/{year} da AT", "resumo": "", "link": hit[1]})
        new_last[str(year)] = n
    # só se grava depois de todos os anos terem sido espreitados sem erro
    mem["ultimas"] = {**previous, **new_last}
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
    head = "A vigia encontrou isto nas fontes oficiais. A rotina segue o `ROTINA.md`.\n\n"
    block = "```json\n" + json.dumps(leads, ensure_ascii=False, indent=2) + "\n```\n"
    corpo = head + "\n".join(lines) + "\n\n" + block
    if len(corpo) > MAX_BODY_CHARS:
        corpo = head + "Lista longa: ver o bloco JSON.\n\n" + block
    return {"tipo": "criar", "titulo": f"Novidades da semana ({now.date().isoformat()})",
            "corpo": corpo, "etiquetas": ["novidade"], "fechar": False}


def _parse_time(text):
    t = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def stale_issues(abertas, now):
    """Ações «criar» para as issues novidade/rever abertas há mais de STALE_DAYS que a rotina não tratou.

    `abertas`: lista do `gh issue list --json number,title,createdAt,updatedAt,labels`. Numa `rever` (que é uma
    issue antiga reaberta) conta a última atividade (updatedAt), porque o createdAt é da issue original.
    Não repete um aviso cujo título exato já exista numa issue aberta.
    """
    titles = {i.get("title") for i in abertas}
    out = []
    for issue in sorted(abertas, key=lambda i: i["number"]):
        names = {label["name"] for label in issue.get("labels", [])}
        if not names & set(WATCHED_LABELS):
            continue
        since = _parse_time(issue["createdAt"])
        if "rever" in names:
            since = max(since, _parse_time(issue.get("updatedAt") or issue["createdAt"]))
        if now - since <= datetime.timedelta(days=STALE_DAYS):
            continue
        title = f"Precisa de ti: a rotina não tratou #{issue['number']}"
        if title in titles:
            continue
        titles.add(title)
        out.append({
            "tipo": "criar",
            "titulo": title,
            "corpo": f"A issue #{issue['number']} («{issue['title']}») está aberta há mais de {STALE_DAYS} dias "
                     f"({since.date().isoformat()}) com a etiqueta `{'rever' if 'rever' in names else 'novidade'}` "
                     "e a rotina não a tratou.\n\nVer a execução da rotina e a Action «Publicar». Para voltar a tentar, "
                     "tirar e voltar a pôr a etiqueta `novidade` (ou `rever`) nessa issue.",
            "etiquetas": ["precisa-de-ti"],
            "fechar": False,
        })
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def exists(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            kind = r.headers.get("Content-Type", "")
            return r.status == 200 and kind.lower().startswith("application/pdf")
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
    parser.add_argument("--abertas", type=Path, help="só no modo semanal: JSON das issues abertas (ver acima)")
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--estado", type=Path, default=STATE)
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    state = load_state(args.estado)
    now = datetime.datetime.now(datetime.timezone.utc)
    if args.modo == "diario":
        state, issues = daily(state, config, fetch, exists, now)
    else:
        stale = []
        if args.abertas is not None:
            try:
                abertas = json.loads(args.abertas.read_text(encoding="utf-8"))
                stale = stale_issues(abertas, now)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                raise SystemExit(f"não consegui ler as issues abertas ({args.abertas}): {e!r}")
        issue = weekly(state, now)
        issues = ([issue] if issue else []) + stale
    args.estado.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.issues is not None:
        args.issues.write_text(json.dumps(issues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{args.modo}: {len(state['pistas'])} pistas por entregar, {len(issues)} issues")


if __name__ == "__main__":
    main()
