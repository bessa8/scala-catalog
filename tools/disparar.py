#!/usr/bin/env python3
"""Dispara a rotina do Claude (endpoint /fire) para uma issue do catálogo.

    python3 tools/disparar.py --issue N
    python3 tools/disparar.py --criadas FICHEIRO   (uma vez por issue `novidade` criada)

Lê ROTINA_URL e ROTINA_TOKEN do ambiente. Sem um deles, não faz nada (exit 0): é o modo
em seco, em que a vigia só abre issues. O token só vai no cabeçalho Authorization e nunca
se escreve.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

PREFIXO = "https://api.anthropic.com/"
REPO = "bessa8/scala-catalog"
NAO_CONFIGURADA = "Rotina não configurada (sem ROTINA_URL/ROTINA_TOKEN): nada disparado."


class SemRedirecionar(urllib.request.HTTPRedirectHandler):
    """Não segue redirecionamentos: o pedido leva o token e só vai para o endereço configurado."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


OPENER = urllib.request.build_opener(SemRedirecionar)


def post(url, headers, body):
    """POST com urllib; devolve (estado HTTP, JSON ou texto). Estado 0 se não houve resposta."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with OPENER.open(req, timeout=60) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, OSError):
        return 0, None
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def disparar(numero, url, token, post=post):
    """Dispara a rotina para a issue `numero`; True se correu bem. Nunca escreve o token."""
    texto = f"Trata a issue #{numero} do repositório {REPO}. Segue o ROTINA.md."
    headers = {"Authorization": f"Bearer {token}", "anthropic-beta": "experimental-cc-routine-2026-04-01",
               "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    try:
        status, resp = post(url, headers, json.dumps({"text": texto}).encode("utf-8"))
    except Exception as e:  # a mensagem pode trazer pedaços do pedido: só o tipo do erro
        print(f"issue #{numero}: o pedido falhou ({type(e).__name__})")
        return False
    if not (isinstance(status, int) and 200 <= status < 300) or not isinstance(resp, dict) or resp.get("type") != "routine_fire":
        print(f"issue #{numero}: a rotina não arrancou (estado HTTP {status})")
        return False
    print(f"issue #{numero}: rotina disparada, sessão {resp.get('claude_code_session_url', '(sem ligação)')}")
    return True


def _numero(texto):
    n = int(texto)
    if n <= 0:
        raise argparse.ArgumentTypeError("tem de ser um número positivo")
    return n


def main(argv=None, env=None, post=post):
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description="Dispara a rotina do catálogo.")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--issue", type=_numero)
    grupo.add_argument("--criadas")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    url, token = (env.get("ROTINA_URL") or "").strip(), (env.get("ROTINA_TOKEN") or "").strip()
    if not url or not token:
        print(NAO_CONFIGURADA)
        print(f"::warning::{NAO_CONFIGURADA}")
        return 0
    if not url.startswith(PREFIXO) or "@" in url.split("/")[2]:
        print(f"ROTINA_URL tem de começar por {PREFIXO}: nada disparado.")
        return 1
    if args.issue is not None:
        numeros = [args.issue]
    else:
        caminho = Path(args.criadas)
        if not caminho.exists():
            print("Sem lista de issues criadas: nada disparado.")
            return 0
        try:
            criadas = json.loads(caminho.read_text(encoding="utf-8"))
            numeros = [c["numero"] for c in criadas if "novidade" in c["etiquetas"]]
            if not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in numeros):
                raise ValueError("número inválido")
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"lista de issues criadas inválida ({args.criadas}): {type(e).__name__}")
            return 1
        if not numeros:
            print("Nenhuma issue novidade criada: nada disparado.")
            return 0
    resultados = [disparar(n, url, token, post) for n in numeros]
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
