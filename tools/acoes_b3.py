"""
LISTA DAS AÇÕES À VISTA (cadastro público de instrumentos da B3)
================================================================
Baixa o InstrumentsConsolidatedFile do dia útil mais recente e grava config/acoes_b3.txt com as ações
do lote padrão: ON, PN e UNIT (sem fracionário, BDR, FII, ETF, recibo, direito). O radar assina essa lista.

Uso: python -X utf8 tools/acoes_b3.py [--data AAAA-MM-DD]
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
from datetime import date, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAIDA = os.path.join(RAIZ, "config", "acoes_b3.txt")
URL_PEDIDO = "https://arquivos.b3.com.br/api/download/requestname?fileName=InstrumentsConsolidatedFile&date={data}"
URL_ARQUIVO = "https://arquivos.b3.com.br/api/download/?token={token}"
TIPOS = {"ON", "PN", "PNA", "PNB", "PNC", "PNA*", "PNB*", "PNC*", "UNT"}
TICKER = re.compile(r"[A-Z0-9]{4}(3|4|5|6|7|8|11)")


def filtrar(linhas) -> list[str]:
    acoes = set()
    for x in csv.DictReader(linhas, delimiter=";"):
        espec = (x.get("SpcfctnCd") or "").split()
        if (x.get("SgmtNm") == "CASH" and x.get("MktNm") == "EQUITY-CASH"
                and x.get("SctyCtgyNm") in ("SHARES", "UNIT") and espec and espec[0] in TIPOS
                and TICKER.fullmatch(x.get("TckrSymb") or "")):
            acoes.add(x["TckrSymb"])
    return sorted(acoes)


def carregar_lista(caminho: str = SAIDA) -> list[str]:
    try:
        with open(caminho, encoding="utf-8") as f:
            return [l.strip().upper() for l in f if l.strip() and not l.lstrip().startswith("#")]
    except OSError:
        return []


def baixar(dia: date) -> list[str]:
    with urllib.request.urlopen(URL_PEDIDO.format(data=dia.isoformat()), timeout=30) as r:
        token = json.load(r)["redirectUrl"].split("token=")[1]
    with urllib.request.urlopen(URL_ARQUIVO.format(token=token), timeout=120) as r:
        texto = r.read().decode("latin-1")
    linhas = texto.splitlines()
    return linhas[1:] if linhas and linhas[0].startswith("Status") else linhas


def main():
    p = argparse.ArgumentParser(description="Atualiza config/acoes_b3.txt pelo cadastro da B3")
    p.add_argument("--data", help="Dia do cadastro (padrão: último dia útil)")
    a = p.parse_args()
    dia = date.fromisoformat(a.data) if a.data else date.today()
    for _ in range(7):                                  # volta até achar um dia com arquivo
        if dia.weekday() < 5:
            try:
                acoes = filtrar(baixar(dia))
                if acoes:
                    break
            except Exception as e:                      # noqa: BLE001 — tenta o dia anterior
                print(f"{dia}: {e}")
        dia -= timedelta(days=1)
    else:
        sys.exit("Não achei o cadastro da B3 nos últimos 7 dias")
    with open(SAIDA, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# Ações à vista (ON/PN/UNIT, lote padrão) — cadastro de instrumentos da B3 de {dia}\n")
        f.write("# Atualize com: python -X utf8 tools/acoes_b3.py\n")
        f.write("\n".join(acoes) + "\n")
    print(f"{len(acoes)} ações ({dia}) → {SAIDA}")


if __name__ == "__main__":
    main()
