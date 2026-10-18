"""
CALIBRAR O ICEBERG EM PREGÕES REAIS
===================================
Roda o motor (corte de volume do sinal desligado) em cada pregão de historico/ e mede, por
papel e faixa de volume absorvido, quantos sinais de iceberg bateram o alvo antes do stop
e o ganho médio em ticks. Grava config/calibracao_iceberg.json, que a tela usa para mostrar
o acerto histórico de cada sinal.

Uso (na pasta do repositório):
  python -X utf8 tools/calibrar_iceberg.py                    # historico/*.csv de todos os papéis
  python -X utf8 tools/calibrar_iceberg.py --ativos PETR4 RENT3 --processos 4
Os pregões vêm de: python -m profitdll.historico --asset X --inicio AAAA-MM-DD --fim AAAA-MM-DD
"""

import argparse
import glob
import json
import logging
import os
import re
import sys
from multiprocessing import Pool

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from core.calibracao import CAMINHO_PADRAO, agregar, faixa_volume   # noqa: E402

ALVO_TICKS = 4
HORIZONTE_SEC = 300
RE_VOL = re.compile(r"\| Vol ([\d,]+)")


def medir_dia(caminho: str) -> dict:
    logging.disable(logging.CRITICAL)
    from core.engine import FlowEngine, EngineConfig
    from replay.csv_ticks import ler_ticks
    from replay.player import executar_replay

    ativo = os.path.basename(caminho).split("_")[0].upper()
    cfg = EngineConfig(defesa_iceberg_vol_sinal={}, defesa_iceberg_vol_sinal_padrao=0)
    sinais, _ = executar_replay(FlowEngine(ativo, cfg), ler_ticks(caminho), velocidade=0,
                                alvo_ticks=ALVO_TICKS, horizonte_sec=HORIZONTE_SEC)
    faixas: dict = {}
    for s in sinais:
        m = RE_VOL.search(s.motivo or "") if s.padrao == "Iceberg" else None
        if not m:
            continue
        v = faixas.setdefault(faixa_volume(int(m.group(1).replace(",", ""))),
                              {"n": 0, "alvo": 0, "stop": 0, "ganho": 0.0})
        v["n"] += 1
        dist = round(abs(s.preco - s.stop) / cfg.tick_size)
        if s.resultado == "alvo":
            v["alvo"] += 1
            v["ganho"] += ALVO_TICKS
        elif s.resultado == "stop":
            v["stop"] += 1
            v["ganho"] -= dist
    return {"ativo": ativo, "arquivo": os.path.basename(caminho), "faixas": faixas}


def main():
    p = argparse.ArgumentParser(description="Calibra o acerto histórico dos sinais de iceberg")
    p.add_argument("--ativos", nargs="*", help="Papéis (padrão: todos os de historico/)")
    p.add_argument("--processos", type=int, default=4, help="Pregões em paralelo (padrão 4)")
    p.add_argument("--saida", default=CAMINHO_PADRAO)
    a = p.parse_args()
    arquivos = sorted(glob.glob(os.path.join(RAIZ, "historico", "*_20*.csv")))
    if a.ativos:
        arquivos = [f for f in arquivos if os.path.basename(f).split("_")[0].upper() in {x.upper() for x in a.ativos}]
    if not arquivos:
        sys.exit("Nenhum pregão em historico/ (baixe com python -m profitdll.historico)")
    with Pool(a.processos) as pool:
        dias = pool.map(medir_dia, arquivos)
    datas = sorted(re.search(r"(\d{4}-\d{2}-\d{2})", d["arquivo"]).group(1) for d in dias)
    tabela = agregar(dias, f"{datas[0]} a {datas[-1]}", ALVO_TICKS, HORIZONTE_SEC)
    with open(a.saida, "w", encoding="utf-8") as f:
        json.dump(tabela, f, ensure_ascii=False, indent=1)
    print(f"{len(dias)} pregões ({tabela['periodo']}) → {a.saida}")


if __name__ == "__main__":
    main()
