"""
CALIBRAÇÃO — acerto histórico dos sinais de iceberg
===================================================
Tabela medida em pregões reais (tools/calibrar_iceberg.py → config/calibracao_iceberg.json):
para cada papel e faixa de volume absorvido pelo iceberg, quantos sinais houve, quantos
bateram o alvo antes do stop e o ganho médio em ticks. A tela mostra isso no lugar da
"força" (fórmula antiga do motor, que segue só para ordenar os sinais entre si).
"""

from __future__ import annotations

import json
import os
from typing import Optional

CAMINHO_PADRAO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "config", "calibracao_iceberg.json")

# Faixas de volume absorvido (ações): limite superior exclusivo
FAIXAS = (("1-2k", 2_000), ("2-5k", 5_000), ("5-10k", 10_000), ("10-20k", 20_000),
          ("20-50k", 50_000), ("50k+", float("inf")))
TODOS = "TODOS"
MIN_SINAIS = 30          # abaixo disso a faixa do papel não basta: usa a de todos os papéis


def faixa_volume(vol: float) -> str:
    for nome, limite in FAIXAS:
        if vol < limite:
            return nome
    return FAIXAS[-1][0]


def carregar(caminho: str = CAMINHO_PADRAO) -> dict:
    """Tabela da calibração; {} se o arquivo não existir ou estiver ilegível."""
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def acerto_iceberg(tabela: dict, ativo: str, vol: float) -> Optional[dict]:
    """{"taxa", "ganho", "n", "faixa", "base"} da faixa do volume; base = papel ou TODOS."""
    faixa = faixa_volume(vol)
    ativos = tabela.get("ativos", {})
    for base in (ativo, TODOS):
        linha = ativos.get(base, {}).get(faixa)
        if linha and linha.get("n", 0) >= MIN_SINAIS:
            return {"taxa": linha["alvo"] / linha["n"], "ganho": linha["ganho"] / linha["n"],
                    "n": linha["n"], "faixa": faixa, "base": base}
    return None


def agregar(dias: list[dict], periodo: str, alvo_ticks: float, horizonte_sec: float) -> dict:
    """Soma os resultados por dia ({"ativo", "faixas": {faixa: {n, alvo, stop, ganho}}}) na tabela."""
    ativos: dict = {}
    for d in dias:
        for base in (d["ativo"], TODOS):
            destino = ativos.setdefault(base, {})
            for faixa, v in d["faixas"].items():
                acc = destino.setdefault(faixa, {"n": 0, "alvo": 0, "stop": 0, "ganho": 0.0})
                for k in acc:
                    acc[k] += v.get(k, 0)
    for faixas in ativos.values():
        for v in faixas.values():
            v["ganho"] = round(v["ganho"], 2)
    return {"periodo": periodo, "alvo_ticks": alvo_ticks, "horizonte_sec": horizonte_sec,
            "dias": len(dias), "ativos": ativos}
