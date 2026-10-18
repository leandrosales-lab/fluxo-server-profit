"""
MOTOR DE DETECÇÃO DE FLUXO — FlowEngine
========================================
Implementa toda a lógica de leitura de fluxo da metodologia
Sociedade dos Traders, processando ticks em tempo real.

Detecta:
  - Iceberg pela corretora PASSIVA (mesma passiva agredida repetidamente no
    mesmo preço sem o preço atravessar); sem passiva, fallback por lote repetido
  - Best Offer Passivo (player sempre no 1º nível)
  - Absorção (muito volume agredido no mesmo nível sem o preço passar)
  - Urgência (player subindo/descendo a escada de preços)
  - Pressão acumulada de fluxo (% compra vs venda)
  - Delta acumulado (volume agredido comprador - vendedor)
  - Exaustão (novas extremidades com cada vez menos agressão)

Emite sinais: BUY / SELL / CLOSE / WAIT
"""

import bisect
import time
import math
import threading
import logging
from collections import deque, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.defesas import DefesaDetector

logger = logging.getLogger("FlowEngine")

# Quantas defesas get_state() entrega: as mais próximas do último preço. Limite de EXIBIÇÃO (tamanho do
# estado e da tela), não é regra de mercado; as demais continuam sendo vigiadas pelo detector.
DEFESAS_NA_TELA = 30


# ──────────────────────────────────────────────────────────────
# TIPOS DE DADOS
# ──────────────────────────────────────────────────────────────

class Side(Enum):
    BUY  = "compra"
    SELL = "venda"
    NONE = "neutro"

class Signal(Enum):
    BUY   = "BUY"
    SELL  = "SELL"
    CLOSE = "CLOSE"
    WAIT  = "WAIT"

class PatternType(Enum):
    ICEBERG     = "Iceberg"
    BEST_OFFER  = "BestOffer"
    ABSORPTION  = "Absorção"
    URGENCY     = "Urgência"
    EXHAUSTION  = "Exaustão"
    NONE        = "Nenhum"


@dataclass
class Tick:
    """Um negócio do Times & Trades."""
    timestamp:  float       # unix timestamp
    price:      float       # preço do negócio
    qty:        int         # quantidade
    broker:     str         # corretora AGRESSORA (ex: "JP MORGAN")
    side:       Side        # agressor: BUY ou SELL
    asset:      str = ""    # ticker (ex: "PETR4")
    passive_broker: str = ""  # corretora PASSIVA (a outra ponta); "" = fonte não informa


@dataclass
class BookLevel:
    """Um nível do Book de Ofertas."""
    price:      float
    qty:        int
    broker:     str
    side:       Side        # BUY = oferta de compra, SELL = oferta de venda
    timestamp:  float = field(default_factory=time.time)


@dataclass
class IcebergCandidate:
    """
    Candidato a Iceberg: ordem passiva escondida renovada no mesmo preço.

    Modo PASSIVA (passive=True): broker é a corretora passiva, side é o lado
    passivo (BUY = compra passiva segurando venda agressora = suporte;
    SELL = venda passiva segurando compra agressora = resistência) e cada
    renovação é uma agressão executada contra ela no nível.

    Modo FALLBACK (passive=False): a fonte não informa a passiva; broker e
    side são do AGRESSOR e a renovação é o mesmo lote repetido no mesmo
    preço (comportamento antigo). É uma heurística fraca.
    """
    broker:         str
    side:           Side
    price:          float
    ref_qty:        int         # lote de referência (primeiro observado)
    renewals:       int = 0     # renovações (modo passiva: execuções contra a passiva)
    total_vol:      int = 0     # volume total absorvido
    first_seen:     float = field(default_factory=time.time)
    last_renewed:   float = field(default_factory=time.time)
    confirmed:      bool = False
    passive:        bool = False    # True = corretora passiva real; False = heurística fraca
    vol_ratio:      float = 0.0     # volume executado / lote médio da janela
    share:          float = 1.0     # fatia da passiva no volume agredido do nível
    confidence:     float = 0.0     # força do iceberg em si (0.0 a 1.0)
    aggressors:     set = field(default_factory=set)   # agressores distintos que bateram

    @property
    def duration(self) -> float:
        return max(self.last_renewed - self.first_seen, 0.0)

    def to_dict(self) -> dict:
        return {
            "broker":          self.broker,
            "passive_broker":  self.broker if self.passive else "",
            "side":            self.side.value,
            "role":            "suporte" if self.side == Side.BUY else "resistência",
            "price":           self.price,
            "renewals":        self.renewals,
            "total_vol":       self.total_vol,
            "vol_ratio":       round(self.vol_ratio, 2),
            "share":           round(self.share, 2),
            "duration_sec":    round(self.duration, 1),
            "aggressors":      len(self.aggressors),
            "confidence":      round(self.confidence, 3),
            "weak_heuristic":  not self.passive,
        }


@dataclass
class Leg:
    """Perna de preço (zigzag) entre dois pivôs, com estatísticas da agressão."""
    direction:      Side        # BUY = perna de alta, SELL = perna de baixa
    start_ts:       float
    end_ts:         float
    start_price:    float
    end_price:      float       # extremidade (máxima da perna de alta / mínima da de baixa)
    vol_with:       int         # volume agredido a favor da perna
    vol_against:    int         # volume agredido contra a perna
    trades:         int         # negócios na perna
    cum_delta_end:  int         # delta acumulado no momento da extremidade

    @property
    def duration(self) -> float:
        return max(self.end_ts - self.start_ts, 1e-6)

    @property
    def speed(self) -> float:
        """Negócios por segundo."""
        return self.trades / self.duration

    @property
    def avg_lot(self) -> float:
        return (self.vol_with + self.vol_against) / max(self.trades, 1)

    def to_dict(self) -> dict:
        return {
            "direction":     self.direction.value,
            "start_price":   self.start_price,
            "end_price":     self.end_price,
            "duration_sec":  round(self.duration, 1),
            "vol_with":      self.vol_with,
            "vol_against":   self.vol_against,
            "trades":        self.trades,
            "speed":         round(self.speed, 2),
            "avg_lot":       round(self.avg_lot, 1),
            "cum_delta_end": self.cum_delta_end,
        }


@dataclass
class ExhaustionEvent:
    """Exaustão confirmada no fim de uma perna (topo ou fundo)."""
    direction:      Side        # lado que exauriu: BUY = compradores cansaram (topo)
    extreme_price:  float
    confirmed_ts:   float       # timestamp (do tick) em que a reversão confirmou
    vol_ratio:      float       # volume da última perna / média das anteriores
    delta_divergence: bool
    speed_ratio:    float
    lot_ratio:      float
    legs_compared:  int
    confidence:     float
    reason:         str

    def to_dict(self) -> dict:
        return {
            "exhausted_side":   self.direction.value,
            "extreme_price":    self.extreme_price,
            "confirmed_ts":     self.confirmed_ts,
            "vol_ratio":        round(self.vol_ratio, 2),
            "delta_divergence": self.delta_divergence,
            "speed_ratio":      round(self.speed_ratio, 2),
            "lot_ratio":        round(self.lot_ratio, 2),
            "legs_compared":    self.legs_compared,
            "confidence":       round(self.confidence, 3),
            "reason":           self.reason,
        }


@dataclass
class FlowSignal:
    """Sinal gerado pelo motor de fluxo."""
    signal:         Signal
    pattern:        PatternType
    direction:      Side
    price:          float
    stop_price:     float
    broker:         str
    confidence:     float       # 0.0 a 1.0
    reason:         str
    timestamp:      float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "signal":     self.signal.value,
            "pattern":    self.pattern.value,
            "direction":  self.direction.value,
            "price":      self.price,
            "stop_price": self.stop_price,
            "broker":     self.broker,
            "confidence": round(self.confidence, 3),
            "reason":     self.reason,
            "timestamp":  self.timestamp,
        }


# Timeframes dos candles servidos em GET /candles (segundos)
CANDLE_TFS = (15, 60, 300, 900, 3600)


# ──────────────────────────────────────────────────────────────
# CONFIGURAÇÕES
# ──────────────────────────────────────────────────────────────

@dataclass
class EngineConfig:
    # Janela de análise de fluxo (segundos)
    flow_window_sec:        float = 30.0

    # % mínimo de volume em um lado para considerar fluxo dominante
    flow_pct_threshold:     float = 65.0

    # Tolerância de preço para considerar o "mesmo nível" (em R$)
    price_tolerance:        float = 0.01

    # Iceberg: variação máxima do lote para ser a "mesma renovação" (%)
    iceberg_lot_tolerance:  float = 20.0

    # Iceberg: número mínimo de renovações para confirmar
    iceberg_min_renewals:   int   = 3

    # Iceberg: timeout (seg) sem renovação antes de descartar
    iceberg_timeout_sec:    float = 10.0

    # Iceberg (passiva): distância em ticks para juntar agressões no "mesmo preço"
    # e tolerância antes de considerar que o preço atravessou o nível
    iceberg_price_ticks:    int   = 0

    # Iceberg (passiva): volume executado contra a passiva >= N x lote médio da janela
    iceberg_vol_ratio:      float = 3.0

    # Iceberg (passiva): fatia mínima da passiva no volume agredido do nível
    # (agressões espalhadas entre várias passivas não são iceberg)
    iceberg_min_share:      float = 0.5

    # Iceberg (passiva): duração mínima (seg) entre a 1ª e a última execução
    iceberg_min_duration_sec: float = 1.0

    # Iceberg (passiva): duração (seg) que dá pontuação cheia na confiança
    iceberg_full_duration_sec: float = 30.0

    # Iceberg (passiva): janela (seg) para calcular o lote médio do ativo
    iceberg_window_sec:     float = 120.0

    # Best Offer: janela de presença no 1º nível (segundos)
    best_offer_window_sec:  float = 15.0

    # Absorção: número de toques mínimos no mesmo nível
    absorption_min_touches: int   = 4

    # Absorção: janela de tempo para contar toques (seg)
    absorption_window_sec:  float = 60.0

    # Absorção: volume agredido mínimo no nível (absoluto)
    absorption_min_volume:  int   = 0

    # Absorção: volume do nível deve ser >= N x a média dos demais níveis da janela
    absorption_vol_ratio:   float = 1.5

    # Urgência: player aparece em N preços diferentes em X seg
    urgency_levels_min:     int   = 3
    urgency_window_sec:     float = 10.0

    # Delta: janela curta (seg) exposta no estado
    delta_window_sec:       float = 30.0

    # Exaustão: ticks de recuo a partir da extremidade para fechar uma perna (zigzag)
    exhaustion_reversal_ticks: int = 3

    # Exaustão: nº mínimo de pernas na mesma direção (fazendo novas extremidades)
    exhaustion_min_legs:    int   = 3

    # Exaustão: volume a favor da última perna / média das anteriores (<= isso = exaustão)
    exhaustion_vol_ratio:   float = 0.6

    # Exaustão: queda de velocidade / lote médio que conta como confirmação extra
    exhaustion_speed_ratio: float = 0.6
    exhaustion_lot_ratio:   float = 0.8

    # Exaustão: as pernas comparadas precisam estar dentro desta janela (seg)
    exhaustion_window_sec:  float = 180.0

    # Exaustão: por quanto tempo (seg) o sinal continua válido após confirmar
    exhaustion_signal_ttl_sec: float = 20.0

    # Exaustão: distância (em ticks) para considerar iceberg/absorção "no mesmo nível"
    exhaustion_confluence_ticks: int = 3

    # Stop automático em ticks atrás do nível do Iceberg
    stop_ticks_behind:      int   = 2
    tick_size:              float = 0.01   # tamanho do tick do ativo

    # ── Defesas (core/defesas.py): regras do professor, origem em cada linha ──
    # Iceberg: o volume executado contra a passiva no preço precisa chegar a este lote (aula-02 03:43–04:09)
    defesa_iceberg_lote_min:   int = 1000
    # Iceberg: 1 giro = alerta, 2 giros confirmam (aula 9393845 05:52); giro = ordem original contra ela no preço
    defesa_iceberg_giros:      int = 2
    # Sniper: agride de volta até N ms depois da agressão contrária no mesmo preço (medido 0–30 ms, aula 9393841)
    defesa_reacao_ms:          int = 30
    # Fantasma: agressões no mesmo preço com o lado dele vazio (aula-02 25:35 "15, 15, 15"; aula 9393842)
    defesa_fantasma_agressoes: int = 3
    # Sniper/fantasma: negócio a N ticks além do nível = defensor ausente (até 3 com a defesa ativa nas
    # aulas 9393833/9393841/9393842; o fim visto foi a 4 e 5 ticks, aula 9393841 10:14:14,10 e 21,03 → 20,98)
    defesa_ausente_ticks:      int = 4
    # E2: distância máxima entre as duas defesas, em ticks (0 tick aula 9393845; 1 tick aula 9393844)
    defesa_e2_ticks:           int = 1
    # Sinal de iceberg: stop no 1º tick além do nível (aula-02 24:15; aula 9393845 06:30)
    defesa_stop_ticks:         int = 1
    # Sinal de iceberg só quando a defesa já absorveu este volume (ações). CALIBRADO, não é regra do curso:
    # 42 pregões reais (17/09–16/10/2026, DLL). O ganho por sinal cresce com o volume absorvido; o corte é onde
    # passa de ~+1 tick (PETR4 ≥50 mil: +1,05; RENT3 ≥5 mil: +1,0 a +2,0). A defesa continua detectada e
    # exibida abaixo do corte; só o sinal espera. Papel sem medida usa o padrão (os icebergs das aulas
    # absorveram de 13 mil a 58 mil).
    defesa_iceberg_vol_sinal:  dict = field(default_factory=lambda: {"PETR4": 50000, "RENT3": 5000})
    defesa_iceberg_vol_sinal_padrao: int = 5000

    # Confiança mínima para emitir sinal
    min_confidence:         float = 0.60

    # Corretoras de alta relevância (peso 2x)
    high_relevance_brokers: list = field(default_factory=lambda: [
        "JP MORGAN", "GOLDMAN SACHS", "BTG PACTUAL", "MERRILL LYNCH",
        "CITY GROUP", "MORGAN STANLEY", "BRADESCO", "ITAU", "AGORA",
        "SANTANDER", "SCOTIA BANK", "XP INC", "UBS"
    ])


# ──────────────────────────────────────────────────────────────
# MOTOR PRINCIPAL
# ──────────────────────────────────────────────────────────────

class FlowEngine:
    """
    Motor de análise de fluxo em tempo real.
    
    Recebe:
      - add_tick(tick): cada negócio do T&T
      - update_book(levels): snapshot do Book de Ofertas
    
    Emite:
      - get_signal(): retorna FlowSignal atual
    """

    def __init__(self, asset: str, config: Optional[EngineConfig] = None):
        self.asset   = asset
        self.cfg     = config or EngineConfig()
        self._lock   = threading.RLock()

        # ── Relógio do engine: tempo do último evento recebido (tick ou book).
        # Todas as janelas de tempo usam este relógio, e não o relógio do
        # computador, para que um pregão gravado (modo replay) se comporte
        # igual ao ao vivo. Antes do primeiro evento, cai no time.time().
        self._clock: float = 0.0

        # ── Histórico de ticks (janela deslizante)
        self._ticks: deque[Tick] = deque(maxlen=5000)

        # ── Times & Trades mais longo para a API (/trades), independente da janela de análise
        self._trades_log: deque[Tick] = deque(maxlen=1000)

        # ── Candles incrementais do dia inteiro, por timeframe (segundos):
        #    tf → {início do candle: candle} + lista ordenada dos inícios
        self._candles: dict[int, dict[int, dict]] = {tf: {} for tf in CANDLE_TFS}
        self._candle_keys: dict[int, list[int]] = {tf: [] for tf in CANDLE_TFS}

        # ── Sinais novos (mesma regra do ReplayPlayer), para desenhar no gráfico
        self._signals_log: deque[dict] = deque(maxlen=1000)
        self._last_signal_key: Optional[tuple] = None

        # ── Resumo do pregão (faixa do Operar), incremental: nada aqui varre o pregão
        self._zerar_resumo()
        self._geracao = 0   # sobe a cada reset(): a tela limpa mesmo que já haja negócios novos

        # ── Book: horário do último snapshot e profundidade já vista (none | top | full)
        self._book_updated: Optional[float] = None
        self._book_depth: str = "none"

        # ── Book atual (preço → BookLevel)
        self._book_buy:  dict[float, BookLevel] = {}
        self._book_sell: dict[float, BookLevel] = {}

        # ── Estado dos Icebergs candidatos
        # chave (fallback sem passiva): (side, price, broker, "agressor")
        self._icebergs: dict[tuple, IcebergCandidate] = {}

        # ── Defesas (iceberg pela passiva, sniper, fantasma, E2): core/defesas.py
        self._defesas = DefesaDetector(self.cfg)
        self._avg_lot_cache = None        # (último tick, relógio, valor) de _iceberg_avg_lot
        self._fonte_com_passiva = False   # vira True no 1º tick com passive_broker; reset() não zera (mesma fonte)

        # ── Histórico de best ask/bid por broker (logs separados para evitar sinal invertido)
        # chave: broker → lista de timestamps em que estava no 1º nível
        self._best_ask_log: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))  # lado venda
        self._best_bid_log: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))  # lado compra

        # ── Toques de preço para absorção
        # chave: price_rounded → deque de (timestamp, qty, side agressor)
        self._price_touches: dict[float, deque] = defaultdict(lambda: deque(maxlen=500))

        # ── Delta acumulado (volume agredido comprador - vendedor) desde o reset
        self._cum_delta: int = 0

        # ── Zigzag para exaustão
        self._zz_dir:          Side  = Side.NONE
        self._zz_extreme:      float = 0.0
        self._zz_extreme_ts:   float = 0.0
        self._zz_extreme_cd:   int   = 0     # delta acumulado na extremidade
        self._zz_origin:       float = 0.0   # preço onde a perna atual começou
        self._zz_origin_ts:    float = 0.0
        self._legs:            deque[Leg] = deque(maxlen=50)
        self._exhaustions:     deque[ExhaustionEvent] = deque(maxlen=20)

        # ── Urgência: preços onde cada player agrediu
        # chave: (broker, side) → deque de (price, timestamp)
        self._urgency_log: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=100))

        # ── Sinal atual
        self._current_signal: FlowSignal = FlowSignal(
            signal=Signal.WAIT, pattern=PatternType.NONE,
            direction=Side.NONE, price=0.0, stop_price=0.0,
            broker="", confidence=0.0, reason="Aguardando dados"
        )

        logger.info(f"FlowEngine iniciado para {asset}")

    # ──────────────────────────────────────────────────────────
    # INGESTÃO DE DADOS
    # ──────────────────────────────────────────────────────────

    def add_tick(self, tick: Tick):
        """Processa um negócio do Times & Trades."""
        with self._lock:
            tick.asset = self.asset
            self._avancar_relogio(tick.timestamp)
            self._ticks.append(tick)
            if tick.passive_broker:
                self._fonte_com_passiva = True
            self._defesas.on_tick(tick)
            self._update_iceberg(tick)
            self._update_urgency(tick)
            self._register_price_touch(tick)
            self._update_delta(tick)
            self._update_zigzag(tick)
            self._trades_log.append(tick)
            self._update_candles(tick)
            self._atualizar_resumo(tick)
            self._analyze()
            self._registrar_sinal()

    def update_book(self, levels: list[BookLevel]):
        """Atualiza o Book de Ofertas com snapshot completo."""
        with self._lock:
            if levels:
                self._avancar_relogio(max(l.timestamp for l in levels))
            self._book_buy.clear()
            self._book_sell.clear()
            for lvl in levels:
                p = round(lvl.price, 2)
                if lvl.side == Side.BUY:
                    self._book_buy[p] = lvl
                else:
                    self._book_sell[p] = lvl
            if levels:
                self._book_updated = max(l.timestamp for l in levels)
                if max(len(self._book_buy), len(self._book_sell)) > 1:
                    self._book_depth = "full"
                elif self._book_depth == "none":
                    self._book_depth = "top"
            self._update_best_offer_log()
            self._defesas.on_book(max(self._book_buy) if self._book_buy else None,
                                  min(self._book_sell) if self._book_sell else None)
            self._analyze()
            self._registrar_sinal()

    # ──────────────────────────────────────────────────────────
    # RELÓGIO DO ENGINE
    # ──────────────────────────────────────────────────────────

    def _avancar_relogio(self, ts: float):
        """O relógio só anda para frente (evento atrasado não volta o tempo)."""
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            return
        if ts > self._clock:
            self._clock = ts

    def _now(self) -> float:
        """Agora, no tempo do mercado: timestamp do último evento recebido."""
        return self._clock if self._clock > 0 else time.time()

    # ──────────────────────────────────────────────────────────
    # DETECÇÃO DE ICEBERG
    # ──────────────────────────────────────────────────────────

    def _update_iceberg(self, tick: Tick):
        """
        Iceberg sem corretora passiva (manual, OCR, DDE): fallback antigo — mesmo
        agressor, mesmo lado, mesmo preço, lote próximo. Heurística fraca.
        Com a passiva (RTD, DLL), as defesas vêm de core/defesas.py.
        """
        self._expire_icebergs(tick)
        if tick.side not in (Side.BUY, Side.SELL):
            return
        if tick.passive_broker:
            return   # com a passiva, iceberg/sniper/fantasma vêm de core/defesas.py
        self._update_iceberg_fallback(tick)

    def _iceberg_tol(self) -> float:
        return self.cfg.iceberg_price_ticks * self.cfg.tick_size + 1e-9

    def _expire_icebergs(self, tick: Tick):
        """Descarta candidatos do fallback sem renovação (timeout)."""
        now = tick.timestamp
        for k, ic in list(self._icebergs.items()):
            motivo = None
            if now - ic.last_renewed > self.cfg.iceberg_timeout_sec:
                motivo = "EXPIROU"
            if motivo is None:
                continue
            if ic.confirmed:
                logger.info(f"Iceberg {motivo}: {ic.broker} @ {ic.price} "
                            f"({ic.renewals} renovações, {ic.total_vol:,} vol total)")
            del self._icebergs[k]

    def _iceberg_avg_lot(self, now: float) -> float:
        """Lote médio agredido na janela iceberg_window_sec (tempo dos ticks)."""
        ultimo = self._ticks[-1] if self._ticks else None
        c = self._avg_lot_cache
        if c is not None and c[0] is ultimo and c[1] == now:
            return c[2]   # mesmo negócio e mesmo relógio: a janela não mudou
        cutoff = now - self.cfg.iceberg_window_sec
        vol = n = 0
        for t in reversed(self._ticks):
            if t.timestamp < cutoff:
                break
            vol += t.qty
            n += 1
        r = vol / n if n else 0.0
        self._avg_lot_cache = (ultimo, now, r)
        return r

    def _confianca_iceberg(self, ic: IcebergCandidate) -> float:
        """Força do iceberg só para ordenar sinais (fórmula que o motor já usava; não é regra do curso)."""
        cfg = self.cfg
        r = min(1.0, ic.renewals / max(3 * cfg.iceberg_min_renewals, 1))
        v = min(1.0, ic.vol_ratio / max(3 * cfg.iceberg_vol_ratio, 1e-9))
        d = min(1.0, ic.duration / max(cfg.iceberg_full_duration_sec, 1e-9))
        conf = 0.35 + 0.15 * r + 0.15 * v + 0.10 * d + 0.10 * ic.share
        if len(ic.aggressors) >= 2:
            conf += 0.05   # vários agressores diferentes batendo na mesma passiva
        return min(0.90, conf)

    def _icebergs_das_defesas(self, nivel: Optional[int] = None, raio: int = 0) -> list[IcebergCandidate]:
        """Icebergs confirmados pelo módulo de defesas, no formato antigo (sinal, estado, confluência).
        Com `nivel`, só os até `raio` ticks dele (o sinal só vale com o preço no nível do iceberg)."""
        ativos = self._defesas.icebergs_ativos(nivel, raio)
        if not ativos:
            return []
        avg_lot = self._iceberg_avg_lot(self._now())
        out = []
        for d in ativos:
            ic = IcebergCandidate(broker=d.corretora, side=Side.BUY if d.lado == "compra" else Side.SELL,
                                  price=d.preco, ref_qty=0, renewals=d.giros, total_vol=d.vol_passivo,
                                  first_seen=d.desde, last_renewed=d.ultima, confirmed=True, passive=True,
                                  aggressors=set(d.agressores))
            ic.share = self._defesas.fatia(d)
            ic.vol_ratio = d.vol_passivo / avg_lot if avg_lot > 0 else 0.0
            ic.confidence = self._confianca_iceberg(ic)
            out.append(ic)
        return out

    def _defesas_na_confluencia(self, lado: str, preco: float, tol: float) -> list:
        """Confluência da exaustão: só soma quando a fonte traz a corretora passiva (RTD, DLL). Em OCR/DDE/
        manual o sniper e o fantasma aparecem na tela, mas não entram no sinal."""
        if not self._fonte_com_passiva:
            return []
        return self._defesas_opostas_perto(lado, preco, tol)

    def _defesas_opostas_perto(self, lado: str, preco: float, tol: float) -> list:
        """Sniper/fantasma confirmados do lado `lado` perto de `preco` (confluência da exaustão)."""
        return [d for d in self._defesas.vigiadas()
                if d.lado == lado and abs(d.preco - preco) <= tol]

    def _update_iceberg_fallback(self, tick: Tick):
        """Comportamento antigo: mesmo agressor, mesmo lado, mesmo preço, lote próximo."""
        now = tick.timestamp
        price_r = round(tick.price, 2)
        key = (tick.side, price_r, tick.broker, "agressor")

        if key in self._icebergs:
            ic = self._icebergs[key]
            # Verificar se o lote está dentro da tolerância
            variation = abs(tick.qty - ic.ref_qty) / max(ic.ref_qty, 1) * 100
            if variation <= self.cfg.iceberg_lot_tolerance:
                ic.renewals    += 1
                ic.total_vol   += tick.qty
                ic.last_renewed = now
                ic.confidence   = min(0.50, 0.25 * ic.renewals / max(self.cfg.iceberg_min_renewals, 1))
                if ic.renewals >= self.cfg.iceberg_min_renewals:
                    ic.confirmed = True
                    logger.debug(f"Iceberg CONFIRMADO: {tick.broker} "
                                 f"{tick.side.value} @ {price_r} "
                                 f"| Renovações: {ic.renewals}")
            else:
                # Lote muito diferente — reset
                del self._icebergs[key]
        else:
            # Primeiro avistamento deste candidato
            self._icebergs[key] = IcebergCandidate(
                broker=tick.broker, side=tick.side,
                price=price_r, ref_qty=tick.qty,
                renewals=1, total_vol=tick.qty,
                first_seen=now, last_renewed=now,
                aggressors={tick.broker},
            )

    # ──────────────────────────────────────────────────────────
    # DETECÇÃO DE BEST OFFER PASSIVO
    # ──────────────────────────────────────────────────────────

    def _relevantes(self) -> set:
        """Corretoras de alta relevância em maiúsculas (montado uma vez por chamada, não por tick)."""
        return {b.upper() for b in self.cfg.high_relevance_brokers}

    def _update_best_offer_log(self):
        """
        Registra quem está no 1º nível do book, separando ask (venda) e bid (compra).
        Nível sem corretora (ex.: TinyBook da DLL) não entra: não há player
        para atribuir e "" viraria um falso sinal de Best Offer.
        """
        now = self._now()

        # Best ask (venda) → log exclusivo do lado vendedor
        if self._book_sell:
            best_sell_price = min(self._book_sell.keys())
            lvl = self._book_sell[best_sell_price]
            if lvl.broker:
                self._best_ask_log[lvl.broker].append(now)

        # Best bid (compra) → log exclusivo do lado comprador
        if self._book_buy:
            best_buy_price = max(self._book_buy.keys())
            lvl = self._book_buy[best_buy_price]
            if lvl.broker:
                self._best_bid_log[lvl.broker].append(now)

    def _count_best_level_brokers(self, log: dict) -> dict:
        """Conta presenças recentes de cada broker em um nível. {broker: count}"""
        now = self._now()
        cutoff = now - self.cfg.best_offer_window_sec
        result = {}
        for broker, times in log.items():
            count = sum(1 for t in times if t >= cutoff)
            if count >= 3:
                result[broker] = count
        return result

    def _get_best_ask_brokers(self) -> dict:
        """Brokers persistentes no best ask (oferta de venda). {broker: count}"""
        return self._count_best_level_brokers(self._best_ask_log)

    def _get_best_bid_brokers(self) -> dict:
        """Brokers persistentes no best bid (oferta de compra). {broker: count}"""
        return self._count_best_level_brokers(self._best_bid_log)

    # ──────────────────────────────────────────────────────────
    # DETECÇÃO DE ABSORÇÃO
    # ──────────────────────────────────────────────────────────

    def _register_price_touch(self, tick: Tick):
        price_r = round(tick.price, 2)
        self._price_touches[price_r].append((tick.timestamp, tick.qty, tick.side))

    def _get_absorbed_levels(self) -> list[tuple]:
        """
        Retorna níveis onde houve absorção na janela: tocados >= min_touches
        E com volume agredido bem acima dos demais níveis (o preço "travou"
        apesar da agressão). Formato: [(price, touches, volume, side_absorvido)],
        onde side_absorvido é o lado agressor dominante (quem foi absorvido).
        Ordenado por volume.
        """
        now = self._now()
        cutoff = now - self.cfg.absorption_window_sec

        # Poda: o relógio só anda para frente, então o que ficou antes do corte nunca
        # mais entra na janela. O filtro abaixo continua valendo para eventos fora de ordem.
        for price in list(self._price_touches):
            touches = self._price_touches[price]
            while touches and touches[0][0] < cutoff:
                touches.popleft()
            if not touches:
                del self._price_touches[price]

        stats = {}
        for price, touches in self._price_touches.items():
            recent = [(q, s) for t, q, s in touches if t >= cutoff]
            if not recent:
                continue
            vol_buy  = sum(q for q, s in recent if s == Side.BUY)
            vol_sell = sum(q for q, s in recent if s == Side.SELL)
            stats[price] = (len(recent), vol_buy, vol_sell)

        total_vol = sum(vb + vs for _, vb, vs in stats.values())
        levels = []
        for price, (n, vol_buy, vol_sell) in stats.items():
            vol = vol_buy + vol_sell
            if n < self.cfg.absorption_min_touches or vol < self.cfg.absorption_min_volume:
                continue
            # Comparar com a média de volume dos OUTROS níveis da janela
            others = len(stats) - 1
            if others > 0:
                avg_others = (total_vol - vol) / others
                if avg_others > 0 and vol < self.cfg.absorption_vol_ratio * avg_others:
                    continue
            side = Side.BUY if vol_buy > vol_sell else Side.SELL
            levels.append((price, n, vol, side))
        return sorted(levels, key=lambda x: -x[2])

    # ──────────────────────────────────────────────────────────
    # DELTA ACUMULADO
    # ──────────────────────────────────────────────────────────

    def _update_delta(self, tick: Tick):
        if tick.side == Side.BUY:
            self._cum_delta += tick.qty
        elif tick.side == Side.SELL:
            self._cum_delta -= tick.qty

    def _calc_window_delta(self, window_sec: float) -> tuple[int, int, int]:
        """(vol_compra, vol_venda, delta) agredidos na janela, relativa ao último tick."""
        if not self._ticks:
            return 0, 0, 0
        cutoff = self._ticks[-1].timestamp - window_sec
        vol_buy = vol_sell = 0
        for t in reversed(self._ticks):
            if t.timestamp < cutoff:
                break
            if t.side == Side.BUY:
                vol_buy += t.qty
            elif t.side == Side.SELL:
                vol_sell += t.qty
        return vol_buy, vol_sell, vol_buy - vol_sell

    # ──────────────────────────────────────────────────────────
    # DETECÇÃO DE EXAUSTÃO (zigzag de pernas + agressão por perna)
    # ──────────────────────────────────────────────────────────

    def _update_zigzag(self, tick: Tick):
        """
        Segmenta o preço em pernas. Uma perna termina quando o preço recua
        exhaustion_reversal_ticks a partir da extremidade; nesse momento a
        perna é fechada e avaliada para exaustão.
        """
        p, ts = tick.price, tick.timestamp
        rev = self.cfg.exhaustion_reversal_ticks * self.cfg.tick_size - 1e-9

        if self._zz_dir == Side.NONE:
            if self._zz_origin_ts == 0.0:
                self._zz_origin, self._zz_origin_ts = p, ts
                self._zz_extreme, self._zz_extreme_ts = p, ts
                self._zz_extreme_cd = self._cum_delta
                return
            if abs(p - self._zz_origin) >= rev:
                self._zz_dir = Side.BUY if p > self._zz_origin else Side.SELL
                self._zz_extreme, self._zz_extreme_ts = p, ts
                self._zz_extreme_cd = self._cum_delta
            return

        up = self._zz_dir == Side.BUY
        if (up and p > self._zz_extreme) or (not up and p < self._zz_extreme):
            self._zz_extreme, self._zz_extreme_ts = p, ts
            self._zz_extreme_cd = self._cum_delta
            return

        if (up and p <= self._zz_extreme - rev) or (not up and p >= self._zz_extreme + rev):
            leg = self._build_leg(self._zz_dir, self._zz_origin_ts, self._zz_extreme_ts,
                                  self._zz_origin, self._zz_extreme, self._zz_extreme_cd)
            self._legs.append(leg)
            self._check_exhaustion(leg, ts)
            # Nova perna na direção oposta, começando na extremidade
            self._zz_origin, self._zz_origin_ts = self._zz_extreme, self._zz_extreme_ts
            self._zz_dir = Side.SELL if up else Side.BUY
            self._zz_extreme, self._zz_extreme_ts = p, ts
            self._zz_extreme_cd = self._cum_delta

    def _build_leg(self, direction: Side, start_ts: float, end_ts: float,
                   start_price: float, end_price: float, cum_delta_end: int) -> Leg:
        vol_with = vol_against = trades = 0
        for t in reversed(self._ticks):
            if t.timestamp > end_ts:
                continue
            if t.timestamp <= start_ts:
                break
            trades += 1
            if t.side == direction:
                vol_with += t.qty
            elif t.side != Side.NONE:
                vol_against += t.qty
        return Leg(direction=direction, start_ts=start_ts, end_ts=end_ts,
                   start_price=start_price, end_price=end_price,
                   vol_with=vol_with, vol_against=vol_against,
                   trades=trades, cum_delta_end=cum_delta_end)

    def _check_exhaustion(self, last: Leg, now_ts: float):
        """
        Exaustão de compra (topo): as últimas pernas de alta fazem máximas
        cada vez mais altas, mas a última teve bem menos agressão compradora
        que as anteriores. Sinais extras: divergência de delta, queda de
        velocidade e de lote médio. A confirmação é o próprio recuo que
        fechou a perna. Exaustão de venda (fundo) é o espelho.
        """
        up = last.direction == Side.BUY
        same = [l for l in self._legs
                if l.direction == last.direction
                and last.end_ts - l.end_ts <= self.cfg.exhaustion_window_sec]
        # Manter só a sequência final de pernas que fazem novas extremidades
        trend = [same[-1]]
        for l in reversed(same[:-1]):
            newer = trend[0]
            if (up and newer.end_price > l.end_price) or (not up and newer.end_price < l.end_price):
                trend.insert(0, l)
            else:
                break
        if len(trend) < self.cfg.exhaustion_min_legs:
            return

        prev = trend[:-1]
        avg_vol   = sum(l.vol_with for l in prev) / len(prev)
        avg_speed = sum(l.speed for l in prev) / len(prev)
        avg_lot   = sum(l.avg_lot for l in prev) / len(prev)
        if avg_vol <= 0:
            return

        vol_ratio = last.vol_with / avg_vol
        if vol_ratio > self.cfg.exhaustion_vol_ratio:
            return

        before = prev[-1]
        divergence  = (last.cum_delta_end < before.cum_delta_end) if up \
                      else (last.cum_delta_end > before.cum_delta_end)
        speed_ratio = last.speed / avg_speed if avg_speed > 0 else 1.0
        lot_ratio   = last.avg_lot / avg_lot if avg_lot > 0 else 1.0

        conf = 0.50 + (self.cfg.exhaustion_vol_ratio - vol_ratio) / self.cfg.exhaustion_vol_ratio * 0.15
        if divergence:
            conf += 0.10
        if speed_ratio <= self.cfg.exhaustion_speed_ratio:
            conf += 0.05
        if lot_ratio <= self.cfg.exhaustion_lot_ratio:
            conf += 0.05
        if len(trend) > self.cfg.exhaustion_min_legs:
            conf += 0.03

        lado = "COMPRADORA (topo)" if up else "VENDEDORA (fundo)"
        details = [f"vol {vol_ratio:.0%} da média de {len(prev)} pernas"]
        if divergence:
            details.append("divergência de delta")
        if speed_ratio <= self.cfg.exhaustion_speed_ratio:
            details.append(f"velocidade {speed_ratio:.0%}")
        if lot_ratio <= self.cfg.exhaustion_lot_ratio:
            details.append(f"lote médio {lot_ratio:.0%}")

        ev = ExhaustionEvent(
            direction=last.direction, extreme_price=last.end_price,
            confirmed_ts=now_ts, vol_ratio=vol_ratio,
            delta_divergence=divergence, speed_ratio=speed_ratio,
            lot_ratio=lot_ratio, legs_compared=len(trend),
            confidence=min(0.90, conf),
            reason=f"Exaustão {lado} @ {last.end_price:.2f} | " + " | ".join(details),
        )
        self._exhaustions.append(ev)
        logger.info(ev.reason)

    def _active_exhaustions(self) -> list[ExhaustionEvent]:
        """Exaustões dentro do TTL cuja extremidade ainda não foi rompida."""
        if not self._ticks:
            return []
        last = self._ticks[-1]
        active = []
        for ev in self._exhaustions:
            if last.timestamp - ev.confirmed_ts > self.cfg.exhaustion_signal_ttl_sec:
                continue
            if ev.direction == Side.BUY and last.price > ev.extreme_price:
                continue
            if ev.direction == Side.SELL and last.price < ev.extreme_price:
                continue
            active.append(ev)
        return active

    # ──────────────────────────────────────────────────────────
    # DETECÇÃO DE URGÊNCIA
    # ──────────────────────────────────────────────────────────

    def _update_urgency(self, tick: Tick):
        """Registra em quantos níveis de preço o player está agredindo."""
        key = (tick.broker, tick.side)
        self._urgency_log[key].append((tick.price, tick.timestamp))

    def _get_urgent_brokers(self) -> list[tuple]:
        """
        Retorna brokers com urgência: apareceram em >= N preços distintos
        em <= X segundos. Formato: [(broker, side, n_levels)]
        """
        now = self._now()
        cutoff = now - self.cfg.urgency_window_sec
        # Poda (mesma lógica da absorção): o que saiu da janela não volta
        for key in list(self._urgency_log):
            history = self._urgency_log[key]
            while history and history[0][1] < cutoff:
                history.popleft()
            if not history:
                del self._urgency_log[key]
        urgent = []
        for (broker, side), history in self._urgency_log.items():
            recent = [(p, t) for p, t in history if t >= cutoff]
            distinct_prices = len(set(round(p, 2) for p, _ in recent))
            if distinct_prices >= self.cfg.urgency_levels_min:
                urgent.append((broker, side, distinct_prices))
        return urgent

    # ──────────────────────────────────────────────────────────
    # CÁLCULO DE PRESSÃO DE FLUXO
    # ──────────────────────────────────────────────────────────

    def _calc_flow_pressure(self) -> tuple[float, float]:
        """
        Calcula % de volume comprador e vendedor na janela de tempo.
        Retorna: (pct_buy, pct_sell)
        """
        now = self._now()
        cutoff = now - self.cfg.flow_window_sec

        vol_buy  = 0
        vol_sell = 0
        relevantes = self._relevantes()

        for tick in reversed(self._ticks):
            if tick.timestamp < cutoff:
                break
            # Dar peso 2x para corretoras de alta relevância
            weight = 2 if tick.broker.upper() in relevantes else 1
            if tick.side == Side.BUY:
                vol_buy  += tick.qty * weight
            else:
                vol_sell += tick.qty * weight

        total = vol_buy + vol_sell
        if total == 0:
            return 50.0, 50.0
        return (vol_buy / total) * 100, (vol_sell / total) * 100

    # ──────────────────────────────────────────────────────────
    # ANÁLISE PRINCIPAL — gera sinal
    # ──────────────────────────────────────────────────────────

    def _analyze(self):
        """Roda todos os detectores e decide o sinal atual."""
        if len(self._ticks) < 5:
            return  # dados insuficientes

        pct_buy, pct_sell = self._calc_flow_pressure()
        flow_side = Side.BUY if pct_buy > pct_sell else Side.SELL
        flow_strength = max(pct_buy, pct_sell)

        # ── 1. Verificar Icebergs confirmados
        nivel_atual = self._defesas.nivel(self._ticks[-1].price)
        fallback_icebergs = [ic for ic in self._icebergs.values() if ic.confirmed]
        confirmed_icebergs = fallback_icebergs + self._icebergs_das_defesas(nivel_atual)

        # ── 2. Verificar Best Offer passivo (ask e bid separados)
        best_ask_brokers = self._get_best_ask_brokers()
        best_bid_brokers = self._get_best_bid_brokers()
        # dicionário unificado usado apenas em _calc_confidence (presença no book = bônus)
        best_offer_brokers = {**best_ask_brokers, **best_bid_brokers}

        # ── 3. Verificar absorção
        absorbed_levels = self._get_absorbed_levels()

        # ── 4. Verificar urgência
        urgent_brokers = self._get_urgent_brokers()

        # ── Montar candidatos de sinal por lado
        buy_candidates  = []
        sell_candidates = []

        # Icebergs → sinal contrário ao fluxo contra eles
        for ic in confirmed_icebergs:
            if ic.passive:
                # Sem tempo de expiração (decisão de 17/10): o sinal só vale com o preço no nível
                if self._defesas.nivel(ic.price) != nivel_atual:
                    continue
                # Corte calibrado de volume absorvido (ver EngineConfig.defesa_iceberg_vol_sinal)
                if ic.total_vol < self.cfg.defesa_iceberg_vol_sinal.get(
                        self.asset, self.cfg.defesa_iceberg_vol_sinal_padrao):
                    continue
                # Corretora passiva real: suporte (compra passiva) → BUY, resistência → SELL
                cand = self._iceberg_passive_candidate(ic, pct_buy, pct_sell, best_ask_brokers,
                                                       best_bid_brokers, absorbed_levels)
                (buy_candidates if ic.side == Side.BUY else sell_candidates).append(cand)
                continue
            broker, side, price = ic.broker, ic.side, ic.price
            # ── Fallback (heurística fraca, sem passiva) — Metodologia Sociedade dos Traders:
            # Iceberg COMPRADOR (BUY) absorvendo agressores vendedores → FOLLOW BUY
            #   Sinal: fluxo vendedor >= threshold E Iceberg está no lado BUY (absorvendo venda)
            # Iceberg VENDEDOR (SELL) absorvendo agressores compradores → FOLLOW SELL
            #   Sinal: fluxo comprador >= threshold E Iceberg está no lado SELL (absorvendo compra)
            if side == Side.BUY:
                # Iceberg comprador: fluxo pode ser vendedor (sendo absorvido) OU comprador (agressivo)
                # Qualquer fluxo dominante com Iceberg BUY = sinal BUY
                flow_ref = max(pct_buy, pct_sell)
                if flow_ref >= self.cfg.flow_pct_threshold:
                    confidence = self._calc_confidence(ic, flow_ref, best_offer_brokers, urgent_brokers)
                    # Bônus se fluxo é vendedor sendo absorvido (setup mais forte)
                    if pct_sell >= self.cfg.flow_pct_threshold:
                        confidence = min(0.99, confidence + 0.10)
                    buy_candidates.append({
                        "pattern":    PatternType.ICEBERG,
                        "broker":     broker,
                        "price":      price,
                        "stop_price": round(price - self.cfg.stop_ticks_behind * self.cfg.tick_size, 2),
                        "confidence": confidence,
                        "reason":     f"Iceberg COMPRADOR de {broker} @ {price:.2f} (heurística fraca) | "
                                      f"{ic.renewals} renovações | Vol absorvido: {ic.total_vol:,} | "
                                      f"Fluxo: {pct_buy:.1f}%C / {pct_sell:.1f}%V"
                    })
            elif side == Side.SELL:
                # Iceberg vendedor: qualquer fluxo dominante + Iceberg SELL = sinal SELL
                flow_ref = max(pct_buy, pct_sell)
                if flow_ref >= self.cfg.flow_pct_threshold:
                    confidence = self._calc_confidence(ic, flow_ref, best_offer_brokers, urgent_brokers)
                    if pct_buy >= self.cfg.flow_pct_threshold:
                        confidence = min(0.99, confidence + 0.10)
                    sell_candidates.append({
                        "pattern":    PatternType.ICEBERG,
                        "broker":     broker,
                        "price":      price,
                        "stop_price": round(price + self.cfg.stop_ticks_behind * self.cfg.tick_size, 2),
                        "confidence": confidence,
                        "reason":     f"Iceberg VENDEDOR de {broker} @ {price:.2f} (heurística fraca) | "
                                      f"{ic.renewals} renovações | Vol absorvido: {ic.total_vol:,} | "
                                      f"Fluxo: {pct_buy:.1f}%C / {pct_sell:.1f}%V"
                    })

        # Best Ask passivo + fluxo vendedor → SELL
        for broker, count in best_ask_brokers.items():
            if pct_sell >= self.cfg.flow_pct_threshold:
                thr = self.cfg.flow_pct_threshold
                conf = min(0.95, 0.50 + (count / 20) * 0.30 + (pct_sell - thr) / (100 - thr) * 0.20)
                last_sell_price = min(self._book_sell.keys()) if self._book_sell else 0
                if last_sell_price:
                    sell_candidates.append({
                        "pattern":    PatternType.BEST_OFFER,
                        "broker":     broker,
                        "price":      last_sell_price,
                        "stop_price": round(last_sell_price + self.cfg.stop_ticks_behind * self.cfg.tick_size, 2),
                        "confidence": conf,
                        "reason":     f"Best Ask PASSIVO: {broker} "
                                      f"({count} snapshots no 1º nível) | Fluxo venda: {pct_sell:.1f}%"
                    })

        # Best Bid passivo + fluxo comprador → BUY
        for broker, count in best_bid_brokers.items():
            if pct_buy >= self.cfg.flow_pct_threshold:
                thr = self.cfg.flow_pct_threshold
                conf = min(0.95, 0.50 + (count / 20) * 0.30 + (pct_buy - thr) / (100 - thr) * 0.20)
                last_buy_price = max(self._book_buy.keys()) if self._book_buy else 0
                if last_buy_price:
                    buy_candidates.append({
                        "pattern":    PatternType.BEST_OFFER,
                        "broker":     broker,
                        "price":      last_buy_price,
                        "stop_price": round(last_buy_price - self.cfg.stop_ticks_behind * self.cfg.tick_size, 2),
                        "confidence": conf,
                        "reason":     f"Best Bid PASSIVO: {broker} "
                                      f"({count} snapshots no 1º nível) | Fluxo compra: {pct_buy:.1f}%"
                    })

        # Urgência → sinal na direção do player urgente
        for broker, side, n_levels in urgent_brokers:
            thr = self.cfg.flow_pct_threshold
            conf = min(0.90, 0.55 + (n_levels / 10) * 0.25 + (flow_strength - thr) / (100 - thr) * 0.20)
            if side == Side.BUY and flow_side == Side.BUY:
                last_price = self._ticks[-1].price if self._ticks else 0
                buy_candidates.append({
                    "pattern":    PatternType.URGENCY,
                    "broker":     broker,
                    "price":      last_price,
                    "stop_price": round(last_price - self.cfg.stop_ticks_behind * self.cfg.tick_size, 2),
                    "confidence": conf,
                    "reason":     f"URGÊNCIA de compra: {broker} em {n_levels} níveis "
                                  f"em {self.cfg.urgency_window_sec:.0f}s | Fluxo: {pct_buy:.1f}%"
                })
            elif side == Side.SELL and flow_side == Side.SELL:
                last_price = self._ticks[-1].price if self._ticks else 0
                sell_candidates.append({
                    "pattern":    PatternType.URGENCY,
                    "broker":     broker,
                    "price":      last_price,
                    "stop_price": round(last_price + self.cfg.stop_ticks_behind * self.cfg.tick_size, 2),
                    "confidence": conf,
                    "reason":     f"URGÊNCIA de venda: {broker} em {n_levels} níveis "
                                  f"em {self.cfg.urgency_window_sec:.0f}s | Fluxo: {pct_sell:.1f}%"
                })

        # Absorção → sinal quando o player que absorvia SAI (nível deixa de ser tocado)
        # (implementado via ausência recente de toques em nível que tinha muitos antes)
        # Nesta versão, sinalizamos quando há nível absorbido E fluxo forte
        if absorbed_levels and flow_strength >= self.cfg.flow_pct_threshold:
            top_level, touches, abs_vol, _ = absorbed_levels[0]
            thr = self.cfg.flow_pct_threshold
            conf = min(0.85, 0.50 + (touches / 20) * 0.25 + (flow_strength - thr) / (100 - thr) * 0.20)
            last_price = self._ticks[-1].price if self._ticks else 0
            if flow_side == Side.BUY and last_price > top_level:
                # Preço rompeu acima do nível absorvido → BUY
                buy_candidates.append({
                    "pattern":    PatternType.ABSORPTION,
                    "broker":     "Detectado por nível",
                    "price":      last_price,
                    "stop_price": round(top_level - self.cfg.stop_ticks_behind * self.cfg.tick_size, 2),
                    "confidence": conf,
                    "reason":     f"Absorção @ {top_level:.2f} ({touches} toques, vol {abs_vol:,}) | "
                                  f"Preço rompeu para {last_price:.2f} | Fluxo: {pct_buy:.1f}%"
                })
            elif flow_side == Side.SELL and last_price < top_level:
                sell_candidates.append({
                    "pattern":    PatternType.ABSORPTION,
                    "broker":     "Detectado por nível",
                    "price":      last_price,
                    "stop_price": round(top_level + self.cfg.stop_ticks_behind * self.cfg.tick_size, 2),
                    "confidence": conf,
                    "reason":     f"Absorção @ {top_level:.2f} ({touches} toques, vol {abs_vol:,}) | "
                                  f"Preço rompeu para {last_price:.2f} | Fluxo: {pct_sell:.1f}%"
                })

        # Exaustão → sinal CONTRA o lado que exauriu (topo → SELL, fundo → BUY).
        # Confluência: iceberg/absorção do lado oposto perto da extremidade soma confiança.
        tol = self.cfg.exhaustion_confluence_ticks * self.cfg.tick_size + 1e-9
        for ev in self._active_exhaustions():
            conf = ev.confidence
            extras = []
            opposite = Side.SELL if ev.direction == Side.BUY else Side.BUY
            near_ics = [ic for ic in fallback_icebergs + self._icebergs_das_defesas(
                            self._defesas.nivel(ev.extreme_price), self.cfg.exhaustion_confluence_ticks + 1)
                        if ic.side == opposite and abs(ic.price - ev.extreme_price) <= tol]
            if any(ic.passive for ic in near_ics):
                conf += 0.10
                extras.append("iceberg oposto (passiva " +
                              ", ".join(sorted({ic.broker for ic in near_ics if ic.passive})) + ")")
            elif near_ics:
                conf += 0.05
                extras.append("iceberg oposto (heurística fraca)")
            outras = self._defesas_na_confluencia(opposite.value, ev.extreme_price, tol)
            if outras and not any(ic.passive for ic in near_ics):
                conf += 0.10
                extras.append("defesa oposta (" +
                              ", ".join(f"{d.tipo} {d.corretora}" for d in outras) + ")")
            if any(abs(p - ev.extreme_price) <= tol and s == ev.direction
                   for p, _, _, s in absorbed_levels):
                conf += 0.05
                extras.append("absorção na extremidade")
            reason = ev.reason + (" | + " + ", ".join(extras) if extras else "")
            last_price = self._ticks[-1].price
            offset = self.cfg.stop_ticks_behind * self.cfg.tick_size
            cand = {
                "pattern":    PatternType.EXHAUSTION,
                "broker":     "Detectado por fluxo",
                "price":      last_price,
                "confidence": min(0.95, conf),
                "reason":     reason,
            }
            if ev.direction == Side.BUY:
                cand["stop_price"] = round(ev.extreme_price + offset, 2)
                sell_candidates.append(cand)
            else:
                cand["stop_price"] = round(ev.extreme_price - offset, 2)
                buy_candidates.append(cand)

        # ── Escolher o melhor sinal
        best_signal = self._pick_best_signal(buy_candidates, sell_candidates)
        if best_signal:
            self._current_signal = best_signal
        else:
            last_price = self._ticks[-1].price if self._ticks else 0
            self._current_signal = FlowSignal(
                signal=Signal.WAIT, pattern=PatternType.NONE,
                direction=Side.NONE, price=last_price, stop_price=0.0,
                broker="", confidence=0.0,
                reason=f"Aguardando setup | Fluxo: {pct_buy:.1f}% compra / {pct_sell:.1f}% venda",
                timestamp=self._now(),
            )

    def _iceberg_passive_candidate(self, ic: IcebergCandidate, pct_buy: float, pct_sell: float,
                                   best_ask: dict, best_bid: dict, absorbed: list) -> dict:
        """
        Candidato de sinal de um iceberg com corretora passiva confirmada.
        Iceberg comprador (passivo na compra) segura a venda agressora → suporte → BUY.
        Iceberg vendedor (passivo na venda) segura a compra agressora → resistência → SELL.
        """
        buy = ic.side == Side.BUY
        conf = ic.confidence
        extras = []
        if ic.broker.upper() in self._relevantes():
            conf += 0.10
            extras.append("corretora relevante")
        if ic.broker in (best_bid if buy else best_ask):
            conf += 0.05
            extras.append("no 1º nível do book")
        pct_contra = pct_sell if buy else pct_buy
        if pct_contra >= self.cfg.flow_pct_threshold:
            conf += 0.05
            extras.append(f"absorvendo fluxo {'vendedor' if buy else 'comprador'} {pct_contra:.0f}%")
        # Confluência com absorção no mesmo nível (absorvido = lado agressor contra o iceberg)
        aggressor = Side.SELL if buy else Side.BUY
        tol = self._iceberg_tol()
        if any(abs(p - ic.price) <= tol and s == aggressor for p, _, _, s in absorbed):
            conf += 0.05
            extras.append("absorção no nível")

        offset = self.cfg.defesa_stop_ticks * self.cfg.tick_size   # 1º tick além do nível (aula-02 24:15)
        lado = "COMPRADOR (suporte)" if buy else "VENDEDOR (resistência)"
        reason = (f"Iceberg {lado} de {ic.broker} (passiva) @ {ic.price:.2f} | "
                  f"{ic.renewals} execuções de {len(ic.aggressors)} agressores | "
                  f"Vol {ic.total_vol:,} ({ic.vol_ratio:.1f}x lote médio, {ic.share:.0%} do nível) | "
                  f"{ic.duration:.0f}s segurando | Fluxo: {pct_buy:.1f}%C / {pct_sell:.1f}%V")
        if extras:
            reason += " | + " + ", ".join(extras)
        return {
            "pattern":    PatternType.ICEBERG,
            "broker":     ic.broker,
            "price":      ic.price,
            "stop_price": round(ic.price - offset if buy else ic.price + offset, 2),
            "confidence": min(0.95, conf),
            "reason":     reason,
        }

    def _calc_confidence(self, ic: IcebergCandidate, flow_pct: float,
                          best_offer: dict, urgent: list) -> float:
        """Calcula confiança do sinal (0.0 a 1.0)."""
        conf = 0.0

        # Base: renovações do iceberg
        conf += min(0.40, ic.renewals / self.cfg.iceberg_min_renewals * 0.25)

        # Força do fluxo
        conf += min(0.25, (flow_pct - self.cfg.flow_pct_threshold) / 35 * 0.25)

        # Broker relevante
        if ic.broker.upper() in self._relevantes():
            conf += 0.15

        # Broker também está no best offer
        if ic.broker in best_offer:
            conf += 0.10

        # Urgência simultânea do mesmo broker
        if any(b == ic.broker for b, _, _ in urgent):
            conf += 0.10

        return min(0.99, conf)

    def _pick_best_signal(self, buy_cands: list, sell_cands: list) -> Optional[FlowSignal]:
        """Escolhe o candidato com maior confiança acima do mínimo."""
        all_cands = [(Side.BUY, c) for c in buy_cands] + [(Side.SELL, c) for c in sell_cands]
        if not all_cands:
            return None

        best_side, best = max(all_cands, key=lambda x: x[1]["confidence"])
        if best["confidence"] < self.cfg.min_confidence:
            return None

        sig = Signal.BUY if best_side == Side.BUY else Signal.SELL
        dir_ = Side.BUY if best_side == Side.BUY else Side.SELL

        return FlowSignal(
            signal=sig, pattern=best["pattern"], direction=dir_,
            price=best["price"], stop_price=best["stop_price"],
            broker=best["broker"], confidence=best["confidence"],
            reason=best["reason"], timestamp=self._now(),
        )

    # ──────────────────────────────────────────────────────────
    # GRÁFICO, TIMES & TRADES E BOOK (alimentam a API das telas)
    # ──────────────────────────────────────────────────────────

    def _update_candles(self, tick: Tick):
        """Atualiza o candle do tick em cada timeframe (negócio atrasado cai no candle dele)."""
        for tf in CANDLE_TFS:
            inicio = int(tick.timestamp // tf * tf)
            c = self._candles[tf].get(inicio)
            if c is None:
                c = {"time": inicio, "open": tick.price, "high": tick.price, "low": tick.price,
                     "close": tick.price, "volume": 0, "buy": 0, "sell": 0, "financeiro": 0.0,
                     "_first": tick.timestamp, "_last": tick.timestamp}
                self._candles[tf][inicio] = c
                bisect.insort(self._candle_keys[tf], inicio)
            else:
                c["high"] = max(c["high"], tick.price)
                c["low"] = min(c["low"], tick.price)
                # abertura e fechamento seguem o horário do negócio, não a ordem de chegada
                if tick.timestamp >= c["_last"]:
                    c["close"], c["_last"] = tick.price, tick.timestamp
                if tick.timestamp < c["_first"]:
                    c["open"], c["_first"] = tick.price, tick.timestamp
            c["volume"] += tick.qty
            c["financeiro"] += tick.price * tick.qty
            if tick.side == Side.BUY:
                c["buy"] += tick.qty
            elif tick.side == Side.SELL:
                c["sell"] += tick.qty

    JANELA_NEGOCIOS_SEC = 300   # negócios/min = média dos últimos 5 min de horário de negócio

    def _zerar_resumo(self):
        self._r_abertura: Optional[tuple] = None   # (horário, preço) do 1º negócio pelo horário
        self._r_ultimo: Optional[tuple] = None     # (horário, preço) do último pelo horário
        self._r_max: Optional[float] = None
        self._r_min: Optional[float] = None
        self._r_qtd = 0
        self._r_qtd_compra = 0
        self._r_financeiro = 0.0
        self._r_recentes: deque = deque()           # horários dos negócios na janela de 5 min
        self._r_saldo: dict[str, int] = defaultdict(int)

    def _atualizar_resumo(self, tick: Tick):
        """
        Atualiza o resumo do dia com um negócio. Regras:
        - abertura e último seguem o HORÁRIO do negócio (um negócio atrasado não vira "último");
        - volume financeiro = Σ preço × quantidade (ações: sem multiplicador);
        - saldo da corretora = compras − vendas em quantidade, contando a ponta agressora e,
          quando a fonte informa, a passiva (agressão de compra: agressora +q, passiva −q).
        """
        p, q, ts = tick.price, tick.qty, tick.timestamp
        if self._r_abertura is None or ts < self._r_abertura[0]:
            self._r_abertura = (ts, p)
        if self._r_ultimo is None or ts >= self._r_ultimo[0]:
            self._r_ultimo = (ts, p)
        self._r_max = p if self._r_max is None else max(self._r_max, p)
        self._r_min = p if self._r_min is None else min(self._r_min, p)
        self._r_qtd += q
        self._r_financeiro += p * q
        if tick.side == Side.BUY:
            self._r_qtd_compra += q
        self._r_recentes.append(ts)
        limite = self._r_ultimo[0] - self.JANELA_NEGOCIOS_SEC
        while self._r_recentes and self._r_recentes[0] <= limite:
            self._r_recentes.popleft()
        sinal = 1 if tick.side == Side.BUY else -1 if tick.side == Side.SELL else 0
        if sinal:
            self._r_saldo[tick.broker] += sinal * q
            if tick.passive_broker:
                self._r_saldo[tick.passive_broker] -= sinal * q

    def get_resumo(self) -> dict:
        """Resumo do pregão para GET /state (bloco "resumo"). Sem negócios, tudo None."""
        with self._lock:
            if not self._r_qtd:
                return {"abertura": None, "maxima": None, "minima": None, "ultimo": None,
                        "volume_financeiro": None, "vwap": None, "agressao_compra_pct": None,
                        "negocios_por_min": None, "saldo_corretoras": []}
            # janela real: até 5 min, mas nunca menos de 1 min (começo do pregão)
            janela = min(self.JANELA_NEGOCIOS_SEC, max(60.0, self._r_ultimo[0] - self._r_abertura[0]))
            saldo = sorted(((b, s) for b, s in self._r_saldo.items() if b),
                           key=lambda x: x[1], reverse=True)
            if len(saldo) > 10:
                saldo = saldo[:5] + saldo[-5:]
            return {
                "abertura":            self._r_abertura[1],
                "maxima":              self._r_max,
                "minima":              self._r_min,
                "ultimo":              self._r_ultimo[1],
                "volume_financeiro":   round(self._r_financeiro, 2),
                "vwap":                round(self._r_financeiro / self._r_qtd, 6),
                "agressao_compra_pct": round(100.0 * self._r_qtd_compra / self._r_qtd, 1),
                "negocios_por_min":    round(len(self._r_recentes) / (janela / 60.0), 1),
                "saldo_corretoras":    [[b, s] for b, s in saldo],
            }

    def _registrar_sinal(self):
        """Guarda cada sinal BUY/SELL novo (chave sinal + padrão + stop; WAIT zera a chave)."""
        sig = self._current_signal
        if sig.signal not in (Signal.BUY, Signal.SELL):
            self._last_signal_key = None
            return
        chave = (sig.signal, sig.pattern, sig.stop_price)
        if chave == self._last_signal_key:
            return
        self._last_signal_key = chave
        self._signals_log.append({
            "timestamp": sig.timestamp, "signal": sig.signal.value, "pattern": sig.pattern.value,
            "price": sig.price, "stop_price": sig.stop_price, "confidence": round(sig.confidence, 3),
            "broker": sig.broker, "reason": sig.reason,
        })

    @staticmethod
    def _trade_dict(t: Tick) -> dict:
        return {"timestamp": t.timestamp, "price": t.price, "qty": t.qty, "side": t.side.value,
                "broker": t.broker, "passive_broker": t.passive_broker}

    def get_trades(self, limit: int = 200) -> list[dict]:
        """Últimos `limit` negócios (no máximo 1000), do mais antigo ao mais novo."""
        with self._lock:
            limit = max(0, min(int(limit), self._trades_log.maxlen))
            return [self._trade_dict(t) for t in list(self._trades_log)[-limit:]] if limit else []

    def get_candles(self, tf: int, since: Optional[float] = None) -> list[dict]:
        """Candles do timeframe `tf` (segundos, um de CANDLE_TFS), a partir de `since` se informado."""
        if tf not in CANDLE_TFS:
            raise ValueError(f"timeframe inválido: {tf} (use um de {list(CANDLE_TFS)})")
        campos = ("time", "open", "high", "low", "close", "volume", "buy", "sell", "financeiro")
        with self._lock:
            chaves = self._candle_keys[tf]
            i = bisect.bisect_left(chaves, since) if since is not None else 0
            return [{k: self._candles[tf][t][k] for k in campos} for t in chaves[i:]]

    def get_signals(self, since: Optional[float] = None) -> list[dict]:
        """Sinais novos registrados, do mais antigo ao mais novo, a partir de `since` se informado."""
        with self._lock:
            return [dict(s) for s in self._signals_log if since is None or s["timestamp"] >= since]

    def get_book(self) -> dict:
        """Último snapshot do book. depth: none (nunca recebeu), top (só o 1º nível) ou full."""
        def nivel(l: BookLevel) -> dict:
            return {"price": l.price, "qty": l.qty, "broker": l.broker}
        with self._lock:
            return {
                "depth":   self._book_depth,
                "bids":    [nivel(self._book_buy[p]) for p in sorted(self._book_buy, reverse=True)],
                "asks":    [nivel(self._book_sell[p]) for p in sorted(self._book_sell)],
                "updated": self._book_updated,
            }

    # ──────────────────────────────────────────────────────────
    # API PÚBLICA
    # ──────────────────────────────────────────────────────────

    def get_signal(self) -> FlowSignal:
        with self._lock:
            return self._current_signal

    def get_state(self) -> dict:
        """Retorna estado completo do motor para debug e para as telas."""
        with self._lock:
            pct_buy, pct_sell = self._calc_flow_pressure()
            confirmed = ([ic.to_dict() for ic in self._icebergs.values() if ic.confirmed]
                         + [ic.to_dict() for ic in self._icebergs_das_defesas()])
            absorbed = [{"price": p, "touches": t, "volume": v, "absorbed_side": s.value}
                        for p, t, v, s in self._get_absorbed_levels()[:3]]
            win_buy, win_sell, win_delta = self._calc_window_delta(self.cfg.delta_window_sec)
            urgent   = [{"broker": b, "side": s.value, "levels": n}
                        for b, s, n in self._get_urgent_brokers()]
            return {
                "asset":              self.asset,
                "tick_count":         len(self._ticks),
                "flow_pct_buy":       round(pct_buy, 1),
                "flow_pct_sell":      round(pct_sell, 1),
                "icebergs_confirmed": confirmed,
                # True se algum iceberg ativo veio do fallback sem corretora passiva
                "icebergs_weak_heuristic": any(i["weak_heuristic"] for i in confirmed),
                "defesas": {
                    "ativas":  [d.to_dict() for d in self._defesas.mais_proximas(
                        self._ticks[-1].price, DEFESAS_NA_TELA)] if self._ticks else [],
                    "eventos": [e.to_dict() for e in self._defesas.eventos(20)],
                },
                "absorbed_levels":    absorbed,
                "delta": {
                    "cumulative":  self._cum_delta,
                    "window":      win_delta,
                    "window_buy":  win_buy,
                    "window_sell": win_sell,
                    "window_sec":  self.cfg.delta_window_sec,
                },
                "legs":               [l.to_dict() for l in list(self._legs)[-6:]],
                "exhaustions":        [e.to_dict() for e in self._active_exhaustions()],
                "urgent_brokers":     urgent,
                "best_ask_brokers":   list(self._get_best_ask_brokers().keys()),
                "best_bid_brokers":   list(self._get_best_bid_brokers().keys()),
                # 10 últimos negócios, do mais antigo ao mais novo (status e relógio das telas)
                "recent_trades":      [self._trade_dict(t) for t in list(self._ticks)[-10:]],
                "resumo":             self.get_resumo(),
                "geracao":            self._geracao,
                "signal":             self._current_signal.to_dict(),
            }

    def reset(self):
        """Reset completo do estado (início de novo dia)."""
        with self._lock:
            self._ticks.clear()
            self._book_buy.clear()
            self._book_sell.clear()
            self._icebergs.clear()
            self._defesas.reset()
            self._best_ask_log.clear()
            self._best_bid_log.clear()
            self._price_touches.clear()
            self._urgency_log.clear()
            self._cum_delta = 0
            self._clock = 0.0
            self._zz_dir = Side.NONE
            self._zz_extreme = self._zz_extreme_ts = 0.0
            self._zz_origin = self._zz_origin_ts = 0.0
            self._zz_extreme_cd = 0
            self._legs.clear()
            self._exhaustions.clear()
            self._trades_log.clear()
            for tf in CANDLE_TFS:
                self._candles[tf].clear()
                self._candle_keys[tf].clear()
            self._signals_log.clear()
            self._zerar_resumo()
            self._geracao += 1
            self._last_signal_key = None
            self._book_updated = None
            self._book_depth = "none"
            self._current_signal = FlowSignal(
                signal=Signal.WAIT, pattern=PatternType.NONE,
                direction=Side.NONE, price=0.0, stop_price=0.0,
                broker="", confidence=0.0, reason="Reset diário"
            )
        logger.info(f"Motor resetado para {self.asset}")
