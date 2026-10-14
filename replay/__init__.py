"""
MODO REPLAY
===========
Roda um pregão gravado em CSV pelo FlowEngine, mede o resultado de cada
sinal (mini backtest) e varre combinações de parâmetros (grid) para
calibrar o engine por ativo. Veja docs/replay.md.
"""

from replay.csv_ticks import GravadorTicks, ler_csv, ler_ticks
from replay.player import (ReplayPlayer, SinalReplay, avaliar_sinais,
                           executar_replay, interpretar_grid, rodar_grid,
                           montar_relatorio)
