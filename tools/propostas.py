"""Escolhe o ramo a tratar no repositório das propostas (funções puras, sem rede).

    python3 -I tools/propostas.py ver --ls-remote FICHEIRO --main SHA --github-output FICHEIRO
    python3 -I tools/propostas.py invalidos --ls-remote FICHEIRO --saida FICHEIRO
    python3 -I tools/propostas.py nome RAMO
    python3 -I tools/propostas.py caminhos FICHEIRO

`ver`: FICHEIRO é a saída de `git ls-remote --heads <url>` do repositório das propostas e SHA o
`main` do scala-catalog. Escreve `ramo=<nome ou vazio>` (o primeiro ramo claude/… de nome válido),
`espelhar=true|false` (true se o main de lá não existe ou difere de SHA) e `invalidos=<n>` (ramos
claude/… de nome inválido). Sai sempre com 0.
`invalidos`: escreve os nomes inválidos, um por linha. `nome`: falha se o nome não for válido.
`caminhos`: lê nomes separados por NUL (`git diff --name-only -z`) e falha se algum não for
permitido ao portão.
"""
import argparse
import re
import sys
from pathlib import Path

PREFIXO = "claude/"
HEADS = "refs/heads/"
NOME = re.compile(r"claude/atualizacao-[0-9]{4}-[0-9]{2}-[0-9]{2}(-[0-9]+)?")


def _heads(ls_remote):
    """(sha, nome) de cada linha `<sha>\\trefs/heads/<nome>`; o resto ignora-se."""
    for linha in ls_remote.splitlines():
        partes = linha.strip().split("\t")
        if len(partes) == 2 and partes[0] and partes[1].startswith(HEADS) and len(partes[1]) > len(HEADS):
            yield partes[0], partes[1][len(HEADS):]


def nome_valido(ramo):
    return re.fullmatch(NOME, ramo) is not None


def _claude(ls_remote):
    return sorted(nome for _, nome in _heads(ls_remote) if nome.startswith(PREFIXO))


def escolher(ls_remote):
    """O primeiro ramo claude/… (por ordem alfabética) de nome válido."""
    validos = [nome for nome in _claude(ls_remote) if nome_valido(nome)]
    return validos[0] if validos else None


def invalidos(ls_remote):
    return [nome for nome in _claude(ls_remote) if not nome_valido(nome)]


def sha_do_main(ls_remote):
    for sha, nome in _heads(ls_remote):
        if nome == "main":
            return sha
    return None


def caminhos_problemas(nomes):
    """Os caminhos que o portão nunca deixaria passar (mesma lista de permitidos que o portão)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # com -I o diretório do script não entra sozinho
    import portao
    maus = []
    for nome in nomes:
        ok = (portao.SAFE_PATH.fullmatch(nome) and not any(parte in ("", ".", "..") for parte in nome.split("/"))
              and (nome.startswith(portao.ALLOWED_PREFIXES) or nome in portao.ALLOWED_FILES))
        if not ok:
            maus.append(nome)
    return maus


def _ver(args):
    with open(args.ls_remote, encoding="utf-8") as f:
        texto = f.read()
    ramo = escolher(texto) or ""
    espelhar = sha_do_main(texto) != args.main.strip()
    maus = len(invalidos(texto))
    with open(args.github_output, "a", encoding="utf-8") as f:
        f.write(f"ramo={ramo}\nespelhar={'true' if espelhar else 'false'}\ninvalidos={maus}\n")
    print(f"propostas: ramo={ramo or '(nenhum)'} espelhar={espelhar} invalidos={maus}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="comando", required=True)
    v = sub.add_parser("ver")
    v.add_argument("--ls-remote", required=True)
    v.add_argument("--main", required=True)
    v.add_argument("--github-output", required=True)
    i = sub.add_parser("invalidos")
    i.add_argument("--ls-remote", required=True)
    i.add_argument("--saida", required=True)
    n = sub.add_parser("nome")
    n.add_argument("ramo")
    c = sub.add_parser("caminhos")
    c.add_argument("ficheiro")
    args = p.parse_args()
    if args.comando == "ver":
        _ver(args)
    elif args.comando == "invalidos":
        with open(args.ls_remote, encoding="utf-8") as f:
            nomes = invalidos(f.read())
        with open(args.saida, "w", encoding="utf-8") as f:
            f.write("".join(f"{nome}\n" for nome in nomes))
        print(f"propostas: {len(nomes)} ramos com nome inválido")
    elif args.comando == "nome":
        if not nome_valido(args.ramo):
            sys.exit("propostas: nome de ramo inválido")
    else:
        with open(args.ficheiro, "rb") as f:
            nomes = [n.decode("utf-8", "replace") for n in f.read().split(b"\0") if n]
        maus = caminhos_problemas(nomes)
        if maus:
            sys.exit(f"propostas: {len(maus)} caminhos que a rotina não pode mexer (o portão recusava-os)")
        print(f"propostas: {len(nomes)} caminhos permitidos")


if __name__ == "__main__":
    main()
