"""
PREGÕES RECENTES DAS AÇÕES (cotações históricas públicas da B3, COTAHIST)
=========================================================================
Baixa os arquivos diários COTAHIST_DDDMMAAAA.ZIP dos últimos pregões (até juntar --pregoes, padrão 25)
e grava historico/diario_b3.json com, por ação do lote padrão no mercado à vista:
  {"PETR4": {"datas": [...], "fechamentos": [...], "volumes": [...]}, ...}   (do mais antigo ao mais recente)
A tela Leilão usa o último fechamento (referência do teórico), a tendência (fechamento contra a média de
20 pregões) e a liquidez (volume financeiro médio). Rode antes do pregão: o arquivo do dia só sai à noite.

Os zips ficam em historico/cotahist/ (não baixa de novo). Uso:
  python -X utf8 tools/cotahist_b3.py [--pregoes 25] [--ate AAAA-MM-DD]
"""

import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA = os.path.join(RAIZ, "historico", "cotahist")
SAIDA = os.path.join(RAIZ, "historico", "diario_b3.json")
URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{d:%d%m%Y}.ZIP"


def ler_linhas(linhas) -> dict:
    """
    Registros 01 do layout COTAHIST (posições do layout público da B3, base 1): DATA 3-10, CODBDI 11-12,
    CODNEG 13-24, TPMERC 25-27, PREULT 109-121 (2 casas), VOLTOT 171-188 (2 casas).
    Só lote padrão (CODBDI 02) no mercado à vista (TPMERC 010). → {ticker: (data, fechamento, volume R$)}
    """
    saida = {}
    for l in linhas:
        if len(l) < 188 or l[:2] != "01" or l[10:12] != "02" or l[24:27] != "010":
            continue
        saida[l[12:24].strip()] = (f"{l[2:6]}-{l[6:8]}-{l[8:10]}", int(l[108:121]) / 100, int(l[170:188]) / 100)
    return saida


def juntar(pregoes: list[dict]) -> dict:
    """Pregões (do mais antigo ao mais recente, cada um de ler_linhas) → séries por papel."""
    series: dict = {}
    for dia in pregoes:
        for ticker, (data, fech, vol) in dia.items():
            s = series.setdefault(ticker, {"datas": [], "fechamentos": [], "volumes": []})
            s["datas"].append(data)
            s["fechamentos"].append(fech)
            s["volumes"].append(vol)
    return series


def baixar_dia(d: date):
    """Linhas do COTAHIST do dia (cache em historico/cotahist/) ou None sem pregão (fim de semana, feriado)."""
    os.makedirs(PASTA, exist_ok=True)
    nome = os.path.join(PASTA, f"COTAHIST_D{d:%d%m%Y}.ZIP")
    if not os.path.exists(nome):
        try:
            with urllib.request.urlopen(URL.format(d=d), timeout=60) as r:
                dados = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        with open(nome, "wb") as f:
            f.write(dados)
    with zipfile.ZipFile(nome) as z:
        return io.TextIOWrapper(z.open(z.namelist()[0]), encoding="latin-1").read().splitlines()


def main():
    p = argparse.ArgumentParser(description="Grava historico/diario_b3.json com os últimos pregões da B3")
    p.add_argument("--pregoes", type=int, default=25)
    p.add_argument("--ate", help="Último dia (padrão: ontem)")
    a = p.parse_args()
    d = date.fromisoformat(a.ate) if a.ate else date.today() - timedelta(days=1)
    pregoes = []
    for _ in range(a.pregoes * 2 + 15):                # fins de semana e feriados não têm arquivo
        if len(pregoes) >= a.pregoes:
            break
        if d.weekday() < 5:
            linhas = baixar_dia(d)
            if linhas is not None:
                pregoes.append(ler_linhas(linhas))
                print(f"  {d:%d/%m/%Y}: {len(pregoes[-1])} papéis")
        d -= timedelta(days=1)
    if not pregoes:
        print("Nenhum pregão baixado", file=sys.stderr)
        return 1
    series = juntar(pregoes[::-1])
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(series, f, ensure_ascii=False)
    print(f"{len(series)} papéis em {len(pregoes)} pregões → {SAIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
