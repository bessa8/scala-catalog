#!/usr/bin/env python3
"""Transforma o relatório da rotina nas issues a abrir e a fechar.

    python3 tools/relatorio.py relatorios/AAAA-MM-DD.json --issues FICHEIRO
"""
import argparse
import json
import re
import sys
from pathlib import Path

MAX_TITLE = 250
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _strings(v):
    return isinstance(v, list) and all(isinstance(s, str) for s in v)


def _data_path(p):
    return (isinstance(p, str) and p.startswith(("tables/", "tax/")) and p.endswith(".json")
            and all(part not in ("", ".", "..") for part in p.split("/")))


def _title(text):
    return text if len(text) <= MAX_TITLE else text[:MAX_TITLE - 1] + "…"


def check(rep):
    _need(isinstance(rep, dict), "o relatório tem de ser um objeto")
    _need(isinstance(rep.get("issue"), int) and not isinstance(rep.get("issue"), bool) and rep["issue"] > 0,
          "«issue» tem de ser o número da issue")
    for key in ("publicado", "precisaDeTi", "semAlteracoes"):
        _need(isinstance(rep.get(key), list), f"falta «{key}»")
    for p in rep["publicado"]:
        _need(isinstance(p, dict) and _data_path(p.get("caminho")),
              "publicado: «caminho» tem de ser um .json em tables/ ou tax/")
        _need(isinstance(p.get("titulo"), str) and p["titulo"].strip(), "publicado: falta «titulo»")
        _need(isinstance(p.get("vigencia"), str) and DATE.match(p["vigencia"]), "publicado: «vigencia» tem de ser AAAA-MM-DD")
        _need(_strings(p.get("fontes")), "publicado: «fontes» tem de ser uma lista de textos")
    for n in rep["precisaDeTi"]:
        _need(isinstance(n, dict) and isinstance(n.get("titulo"), str) and n["titulo"].strip()
              and isinstance(n.get("texto"), str) and _strings(n.get("fontes")),
              "precisaDeTi: precisa de «titulo», «texto» e «fontes»")
    for s in rep["semAlteracoes"]:
        _need(isinstance(s, dict) and isinstance(s.get("pista"), str) and isinstance(s.get("motivo"), str),
              "semAlteracoes: precisa de «pista» e «motivo»")


def actions(rep):
    check(rep)
    out = []
    pub = rep["publicado"]
    if pub:
        lines = []
        for p in pub:
            lines.append(f"- **{p['titulo']}** (`{p['caminho']}`), em vigor a {p['vigencia']}")
            lines += [f"  - Fonte: {s}" for s in p["fontes"]]
        out.append({"tipo": "criar", "titulo": _title("Publicado: " + "; ".join(p["titulo"] for p in pub)),
                    "corpo": "\n".join(lines), "etiquetas": ["publicado"], "fechar": True})
    for n in rep["precisaDeTi"]:
        corpo = n["texto"]
        if n["fontes"]:
            corpo += "\n\nFontes:\n" + "\n".join(f"- {s}" for s in n["fontes"])
        corpo += "\n\nPara a rotina voltar a esta questão: comentar com a decisão e pôr a etiqueta `rever`."
        out.append({"tipo": "criar", "titulo": _title(f"Precisa de ti: {n['titulo']}"), "corpo": corpo,
                    "etiquetas": ["precisa-de-ti"], "fechar": False})
    resumo = ([f"- Publicado: {p['titulo']}" for p in pub]
              + [f"- Precisa de ti: {n['titulo']}" for n in rep["precisaDeTi"]]
              + [f"- Sem alterações: {s['pista']} ({s['motivo']})" for s in rep["semAlteracoes"]])
    out.append({"tipo": "fechar", "numero": rep["issue"], "comentario": "Tratada.\n\n" + "\n".join(resumo)})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("relatorio", type=Path)
    parser.add_argument("--issues", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rep = json.loads(args.relatorio.read_text(encoding="utf-8"))
        acts = actions(rep)
    except (OSError, ValueError) as e:  # JSON inválido também é ValueError
        print(f"relatório inválido ({args.relatorio}): {e}")
        sys.exit(1)
    args.issues.write_text(json.dumps(acts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
