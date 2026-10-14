"""
PLAYER DE REPLAY + MINI BACKTEST + GRID
========================================
  - ReplayPlayer: entrega os ticks gravados ao engine, na velocidade
    pedida (0 = o mais rápido possível, 1 = tempo real, N = N vezes),
    e anota cada sinal NOVO (BUY/SELL) que o engine emitir.
  - avaliar_sinais: para cada sinal, olha os ticks seguintes dentro de um
    horizonte e diz se o preço andou `alvo_ticks` a favor ANTES de tocar
    o stop do sinal. Também mede MFE (máximo a favor) e MAE (máximo
    contra), em ticks.
  - rodar_grid: repete o replay para cada combinação de parâmetros do
    EngineConfig e resume nº de sinais e taxa de acerto.

O engine usa o tempo do próprio tick (relógio do engine), então o mesmo
arquivo produz sempre os mesmos sinais, em qualquer velocidade.
"""

import csv
import dataclasses
import itertools
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from core.engine import FlowEngine, EngineConfig, PatternType, Signal, Side, Tick
from replay.csv_ticks import FUSO_B3

logger = logging.getLogger("Replay")

RESULTADO_ALVO = "alvo"
RESULTADO_STOP = "stop"
RESULTADO_NENHUM = "nenhum"        # nem alvo nem stop dentro do horizonte


@dataclass
class SinalReplay:
    """Um sinal emitido durante o replay e o que aconteceu depois dele."""
    indice:       int           # posição do tick que gerou o sinal
    timestamp:    float
    sinal:        str           # BUY / SELL
    padrao:       str           # Exaustão, Absorção, Iceberg...
    preco:        float         # preço de entrada (preço do tick do sinal)
    stop:         float
    confianca:    float
    corretora:    str
    motivo:       str
    resultado:    str = ""      # alvo / stop / nenhum
    mfe_ticks:    float = 0.0   # máximo a favor (ticks)
    mae_ticks:    float = 0.0   # máximo contra (ticks, número positivo)
    segundos_ate_resultado: float = 0.0

    @property
    def direcao(self) -> int:
        return 1 if self.sinal == Signal.BUY.value else -1

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["hora"] = _hora(self.timestamp)
        return d


def _hora(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, FUSO_B3).strftime("%d/%m/%Y %H:%M:%S.%f")[:-3]
    except (OverflowError, OSError, ValueError):
        return str(ts)


# ──────────────────────────────────────────────────────────────
# PLAYER
# ──────────────────────────────────────────────────────────────

class ReplayPlayer:
    """Entrega uma lista de ticks ao engine e coleta os sinais novos."""

    def __init__(self, engine: FlowEngine, ticks: list[Tick],
                 velocidade: float = 0.0, reset_diario: bool = True,
                 ao_sinal: Optional[Callable[[SinalReplay], None]] = None):
        self.engine       = engine
        self.ticks        = ticks
        self.velocidade   = max(0.0, float(velocidade or 0.0))
        self.reset_diario = reset_diario
        self.ao_sinal     = ao_sinal
        self.sinais: list[SinalReplay] = []
        self.ticks_entregues = 0
        self._parar = False

    def parar(self):
        self._parar = True

    def rodar(self) -> list[SinalReplay]:
        ultima_chave = None
        ultimo_dia = None
        t0_parede = t0_mercado = None

        for i, tick in enumerate(self.ticks):
            if self._parar:
                break

            # Ritmo: 0 = máximo; 1 = tempo real; N = N vezes mais rápido
            if self.velocidade > 0:
                if t0_parede is None:
                    t0_parede, t0_mercado = time.monotonic(), tick.timestamp
                alvo = t0_parede + (tick.timestamp - t0_mercado) / self.velocidade
                espera = alvo - time.monotonic()
                if espera > 0:
                    time.sleep(espera)

            # Pregão novo no arquivo → reset (como o reset diário ao vivo)
            if self.reset_diario:
                dia = _dia(tick.timestamp)
                if ultimo_dia is not None and dia != ultimo_dia:
                    self.engine.reset()
                    ultima_chave = None
                ultimo_dia = dia

            self.engine.add_tick(tick)
            self.ticks_entregues += 1

            sig = self.engine.get_signal()
            if sig.signal in (Signal.BUY, Signal.SELL):
                chave = (sig.signal, sig.pattern, sig.stop_price)
                if chave != ultima_chave:
                    s = SinalReplay(
                        indice=i, timestamp=tick.timestamp, sinal=sig.signal.value,
                        padrao=sig.pattern.value, preco=tick.price,
                        stop=sig.stop_price, confianca=round(sig.confidence, 3),
                        corretora=sig.broker, motivo=sig.reason,
                    )
                    self.sinais.append(s)
                    if self.ao_sinal:
                        self.ao_sinal(s)
                ultima_chave = chave
            else:
                ultima_chave = None
        return self.sinais


def _dia(ts: float):
    try:
        return datetime.fromtimestamp(ts, FUSO_B3).date()   # pregão = dia na B3
    except (OverflowError, OSError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────
# MINI BACKTEST
# ──────────────────────────────────────────────────────────────

def avaliar_sinais(sinais: list[SinalReplay], ticks: list[Tick], tick_size: float,
                   alvo_ticks: float = 4, horizonte_sec: float = 300.0,
                   stop_padrao_ticks: float = 2) -> list[SinalReplay]:
    """
    Para cada sinal: o preço andou `alvo_ticks` a favor antes de tocar o stop?
    Se o stop do sinal estiver do lado errado (ou colado na entrada), usa
    `stop_padrao_ticks`. MFE/MAE são medidos em todo o horizonte.
    """
    tk = tick_size if tick_size > 0 else 0.01
    eps = 1e-9
    for s in sinais:
        d = s.direcao
        entrada = s.preco
        stop = s.stop
        if (entrada - stop) * d <= eps:
            stop = entrada - d * stop_padrao_ticks * tk
        mfe = mae = 0.0
        resultado, dt_res = RESULTADO_NENHUM, 0.0
        for t in ticks[s.indice + 1:]:
            dt = t.timestamp - s.timestamp
            if dt > horizonte_sec:
                break
            mov = round((t.price - entrada) * d / tk, 6)
            mfe = max(mfe, mov)
            mae = min(mae, mov)
            if resultado == RESULTADO_NENHUM:
                if mov >= alvo_ticks - eps:
                    resultado, dt_res = RESULTADO_ALVO, dt
                elif (t.price - stop) * d <= eps:
                    resultado, dt_res = RESULTADO_STOP, dt
        s.resultado = resultado
        s.mfe_ticks = round(mfe, 2)
        s.mae_ticks = round(abs(mae), 2)
        s.segundos_ate_resultado = round(dt_res, 3)
    return sinais


def resumir(sinais: list[SinalReplay]) -> dict:
    """Contagem por resultado e taxa de acerto (alvo / total de sinais)."""
    n = len(sinais)
    alvos = sum(1 for s in sinais if s.resultado == RESULTADO_ALVO)
    stops = sum(1 for s in sinais if s.resultado == RESULTADO_STOP)
    return {
        "n_sinais":      n,
        "alvos":         alvos,
        "stops":         stops,
        "sem_resultado": n - alvos - stops,
        "taxa_acerto":   round(alvos / n, 4) if n else 0.0,
        "taxa_decididos": round(alvos / (alvos + stops), 4) if (alvos + stops) else 0.0,
        "mfe_medio":     round(sum(s.mfe_ticks for s in sinais) / n, 2) if n else 0.0,
        "mae_medio":     round(sum(s.mae_ticks for s in sinais) / n, 2) if n else 0.0,
    }


# ──────────────────────────────────────────────────────────────
# EXECUÇÃO COMPLETA + RELATÓRIO
# ──────────────────────────────────────────────────────────────

def executar_replay(engine: FlowEngine, ticks: list[Tick], velocidade: float = 0.0,
                    alvo_ticks: float = 4, horizonte_sec: float = 300.0,
                    ao_sinal=None) -> tuple[list[SinalReplay], ReplayPlayer]:
    player = ReplayPlayer(engine, ticks, velocidade=velocidade, ao_sinal=ao_sinal)
    sinais = player.rodar()
    avaliar_sinais(sinais, ticks, engine.cfg.tick_size, alvo_ticks, horizonte_sec,
                   engine.cfg.stop_ticks_behind)
    return sinais, player


def montar_relatorio(ticks: list[Tick], sinais: list[SinalReplay],
                     alvo_ticks: float, horizonte_sec: float,
                     listar: int = 50) -> str:
    linhas = []
    linhas.append("=" * 72)
    linhas.append("  RELATÓRIO DO REPLAY")
    linhas.append("=" * 72)
    linhas.append(f"  Ticks:     {len(ticks)}")
    if ticks:
        linhas.append(f"  Período:   {_hora(ticks[0].timestamp)} → {_hora(ticks[-1].timestamp)}")
    linhas.append(f"  Critério:  alvo de {alvo_ticks:g} ticks a favor antes do stop do sinal, "
                  f"em até {horizonte_sec:g}s")
    linhas.append("")
    linhas.append(f"  {'Padrão':<12}{'Sinais':>7}{'Alvo':>7}{'Stop':>7}{'Nenhum':>8}"
                  f"{'Acerto':>9}{'MFE méd':>9}{'MAE méd':>9}")
    for p in PatternType:
        if p == PatternType.NONE:
            continue
        r = resumir([s for s in sinais if s.padrao == p.value])
        acerto = f"{r['taxa_acerto']:.0%}" if r["n_sinais"] else "-"
        linhas.append(f"  {p.value:<12}{r['n_sinais']:>7}{r['alvos']:>7}{r['stops']:>7}"
                      f"{r['sem_resultado']:>8}{acerto:>9}{r['mfe_medio']:>9}{r['mae_medio']:>9}")
    r = resumir(sinais)
    acerto = f"{r['taxa_acerto']:.0%}" if r["n_sinais"] else "-"
    linhas.append(f"  {'TOTAL':<12}{r['n_sinais']:>7}{r['alvos']:>7}{r['stops']:>7}"
                  f"{r['sem_resultado']:>8}{acerto:>9}{r['mfe_medio']:>9}{r['mae_medio']:>9}")

    if sinais:
        linhas.append("")
        linhas.append(f"  Sinais (mostrando {min(listar, len(sinais))} de {len(sinais)}):")
        for s in sinais[:listar]:
            linhas.append(
                f"  {_hora(s.timestamp)[11:]}  {s.sinal:<4} {s.padrao:<10} "
                f"@ {s.preco:<10g} stop {s.stop:<10g} conf {s.confianca:.2f} → "
                f"{s.resultado.upper():<6} MFE {s.mfe_ticks:g} / MAE {s.mae_ticks:g}")
    linhas.append("=" * 72)
    return "\n".join(linhas)


def salvar_sinais_csv(caminho: str, sinais: list[SinalReplay]):
    campos = ["hora", "timestamp", "sinal", "padrao", "preco", "stop", "confianca",
              "resultado", "mfe_ticks", "mae_ticks", "segundos_ate_resultado",
              "corretora", "motivo", "indice"]
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for s in sinais:
            w.writerow(s.to_dict())


# ──────────────────────────────────────────────────────────────
# GRID DE CALIBRAÇÃO
# ──────────────────────────────────────────────────────────────

def interpretar_grid(specs: list[str]) -> dict[str, list]:
    """
    ["exhaustion_vol_ratio=0.5,0.6", "exhaustion_reversal_ticks=2,3"]
    → {"exhaustion_vol_ratio": [0.5, 0.6], "exhaustion_reversal_ticks": [2, 3]}
    Os valores são convertidos para o tipo do campo no EngineConfig.
    """
    campos = {f.name: f for f in dataclasses.fields(EngineConfig)}
    padrao = EngineConfig()
    grade = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"Grid inválido {spec!r}: use nome=v1,v2,v3")
        nome, valores = spec.split("=", 1)
        nome = nome.strip()
        if nome not in campos:
            raise ValueError(f"Parâmetro desconhecido no grid: {nome!r}. "
                             f"Opções: {', '.join(sorted(campos))}")
        tipo = type(getattr(padrao, nome))
        if tipo not in (int, float, bool, str):
            raise ValueError(f"Parâmetro {nome!r} não pode ser variado no grid")
        lista = []
        for v in valores.split(","):
            v = v.strip()
            if not v:
                continue
            if tipo is bool:
                lista.append(v.lower() in ("1", "true", "sim", "s", "yes"))
            elif tipo is int:
                lista.append(int(float(v)))
            else:
                lista.append(tipo(v))
        if not lista:
            raise ValueError(f"Grid sem valores para {nome!r}")
        grade[nome] = lista
    return grade


def rodar_grid(ticks: list[Tick], grade: dict[str, list],
               base_cfg: Optional[EngineConfig] = None, asset: str = "REPLAY",
               alvo_ticks: float = 4, horizonte_sec: float = 300.0) -> list[dict]:
    """Um replay (velocidade máxima) por combinação. Retorna uma linha por combinação."""
    base_cfg = base_cfg or EngineConfig()
    nomes = list(grade)
    linhas = []
    log_engine = logging.getLogger("FlowEngine")
    nivel_antigo = log_engine.level
    log_engine.setLevel(logging.WARNING)      # o engine loga cada exaustão: silenciar
    try:
        for combo in itertools.product(*(grade[n] for n in nomes)):
            ajustes = dict(zip(nomes, combo))
            cfg = dataclasses.replace(base_cfg, **ajustes)
            engine = FlowEngine(asset, cfg)
            sinais, _ = executar_replay(engine, ticks, 0.0, alvo_ticks, horizonte_sec)
            linha = dict(ajustes)
            linha.update(resumir(sinais))
            for p in PatternType:
                if p != PatternType.NONE:
                    linha[f"n_{_normalizar_padrao(p.value)}"] = sum(
                        1 for s in sinais if s.padrao == p.value)
            linhas.append(linha)
    finally:
        log_engine.setLevel(nivel_antigo)
    return linhas


def _normalizar_padrao(nome: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", nome)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def montar_tabela_grid(linhas: list[dict], nomes: list[str], top: int = 20) -> str:
    """Tabela ordenada por taxa de acerto (desempate: mais sinais)."""
    ordenadas = sorted(linhas, key=lambda l: (-l["taxa_acerto"], -l["n_sinais"]))
    cab = "  ".join(f"{n:>26}" if len(n) > 12 else f"{n:>12}" for n in nomes)
    out = ["=" * 72, f"  GRID — {len(linhas)} combinações (melhores primeiro)", "=" * 72,
           f"{cab}  {'sinais':>6} {'alvo':>5} {'stop':>5} {'acerto':>7} {'decid.':>7}"]
    for l in ordenadas[:top]:
        vals = "  ".join((f"{l[n]!s:>26}" if len(n) > 12 else f"{l[n]!s:>12}") for n in nomes)
        out.append(f"{vals}  {l['n_sinais']:>6} {l['alvos']:>5} {l['stops']:>5} "
                   f"{l['taxa_acerto']:>7.0%} {l['taxa_decididos']:>7.0%}")
    out.append("=" * 72)
    return "\n".join(out)


def salvar_grid_csv(caminho: str, linhas: list[dict]):
    if not linhas:
        return
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)
