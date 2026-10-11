#!/usr/bin/env python3
"""Escolhe o ramo a tratar no repositório das propostas (funções puras, sem rede).

    python3 tools/propostas.py ver --ls-remote FICHEIRO --main SHA --github-output FICHEIRO

FICHEIRO é a saída de `git ls-remote --heads <url>` do repositório das propostas e SHA o
`main` do scala-catalog. Escreve `ramo=<nome ou vazio>` e `espelhar=true|false` (true se o
main de lá não existe ou difere de SHA). Sai sempre com 0.
"""
import argparse
import re

PREFIXO = "claude/"
HEADS = "refs/heads/"
NOME = re.compile(r"claude/atualizacao-[0-9]{4}-[0-9]{2}-[0-9]{2}(-[0-9]+)?")


def _heads(ls_remote):
    """(sha, nome) de cada linha `<sha>\\trefs/heads/<nome>`; o resto ignora-se."""
    for linha in ls_remote.splitlines():
        partes = linha.strip().split("\t")
        if len(partes) == 2 and partes[0] and partes[1].startswith(HEADS) and len(partes[1]) > len(HEADS):
            yield partes[0], partes[1][len(HEADS):]


def escolher(ls_remote):
    nomes = sorted(nome for _, nome in _heads(ls_remote) if nome.startswith(PREFIXO))
    return nomes[0] if nomes else None


def nome_valido(ramo):
    return re.fullmatch(NOME, ramo) is not None


def sha_do_main(ls_remote):
    for sha, nome in _heads(ls_remote):
        if nome == "main":
            return sha
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("comando", choices=["ver"])
    p.add_argument("--ls-remote", required=True)
    p.add_argument("--main", required=True)
    p.add_argument("--github-output", required=True)
    args = p.parse_args()
    with open(args.ls_remote, encoding="utf-8") as f:
        texto = f.read()
    ramo = escolher(texto) or ""
    espelhar = sha_do_main(texto) != args.main.strip()
    with open(args.github_output, "a", encoding="utf-8") as f:
        f.write(f"ramo={ramo}\nespelhar={'true' if espelhar else 'false'}\n")
    print(f"propostas: ramo={ramo or '(nenhum)'} espelhar={espelhar}")


if __name__ == "__main__":
    main()
