"""
MOTOR DE DETECÇÃO DE FLUXO — FlowEngine
========================================
Implementa toda a lógica de leitura de fluxo da metodologia
Sociedade dos Traders, processando ticks em tempo real.

Detecta:
  - Iceberg por corretora (lote renovando no mesmo preço)
  - Best Offer Passivo (player sempre no 1º nível)
  - Absorção (preço travado no mesmo nível)
  - Urgência (player subindo/descendo a escada de preços)
  - Pressão acumulada de fluxo (% compra vs venda)

Emite sinais: BUY / SELL / CLOSE / WAIT
"""

import time
import math
import threading
import logging
from collections import deque, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("FlowEngine")


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
    NONE        = "Nenhum"


@dataclass
class Tick:
    """Um negócio do Times & Trades."""
    timestamp:  float       # unix timestamp
    price:      float       # preço do negócio
    qty:        int         # quantidade
    broker:     str         # corretora (ex: "JP MORGAN")
    side:       Side        # agressor: BUY ou SELL
    asset:      str = ""    # ticker (ex: "PETR4")


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
    """Candidato a Iceberg: lote se renovando no mesmo preço."""
    broker:         str
    side:           Side
    price:          float
    ref_qty:        int         # lote de referência (primeiro observado)
    renewals:       int = 0     # quantas vezes o lote foi renovado
    total_vol:      int = 0     # volume total absorvido
    first_seen:     float = field(default_factory=time.time)
    last_renewed:   float = field(default_factory=time.time)
    confirmed:      bool = False


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

    # Best Offer: janela de presença no 1º nível (segundos)
    best_offer_window_sec:  float = 15.0

    # Absorção: número de toques mínimos no mesmo nível
    absorption_min_touches: int   = 4

    # Absorção: janela de tempo para contar toques (seg)
    absorption_window_sec:  float = 60.0

    # Urgência: player aparece em N preços diferentes em X seg
    urgency_levels_min:     int   = 3
    urgency_window_sec:     float = 10.0

    # Stop automático em ticks atrás do nível do Iceberg
    stop_ticks_behind:      int   = 2
    tick_size:              float = 0.01   # tamanho do tick do ativo

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

        # ── Histórico de ticks (janela deslizante)
        self._ticks: deque[Tick] = deque(maxlen=5000)

        # ── Book atual (preço → BookLevel)
        self._book_buy:  dict[float, BookLevel] = {}
        self._book_sell: dict[float, BookLevel] = {}

        # ── Estado dos Icebergs candidatos
        # chave: (broker, side, price_rounded)
        self._icebergs: dict[tuple, IcebergCandidate] = {}

        # ── Histórico de best ask/bid por broker (logs separados para evitar sinal invertido)
        # chave: broker → lista de timestamps em que estava no 1º nível
        self._best_ask_log: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))  # lado venda
        self._best_bid_log: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))  # lado compra

        # ── Toques de preço para absorção
        # chave: price_rounded → lista de timestamps
        self._price_touches: dict[float, deque] = defaultdict(lambda: deque(maxlen=500))

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
            self._ticks.append(tick)
            self._update_iceberg(tick)
            self._update_urgency(tick)
            self._register_price_touch(tick.price)
            self._analyze()

    def update_book(self, levels: list[BookLevel]):
        """Atualiza o Book de Ofertas com snapshot completo."""
        with self._lock:
            self._book_buy.clear()
            self._book_sell.clear()
            for lvl in levels:
                p = round(lvl.price, 2)
                if lvl.side == Side.BUY:
                    self._book_buy[p] = lvl
                else:
                    self._book_sell[p] = lvl
            self._update_best_offer_log()
            self._analyze()

    # ──────────────────────────────────────────────────────────
    # DETECÇÃO DE ICEBERG
    # ──────────────────────────────────────────────────────────

    def _update_iceberg(self, tick: Tick):
        """
        Detecta renovação de lote Iceberg.
        Heurística: mesmo broker, mesmo lado, mesmo preço (~), lote próximo.
        """
        now = tick.timestamp
        price_r = round(tick.price, 2)
        key = (tick.broker, tick.side, price_r)

        # Limpar icebergs expirados
        expired = [k for k, ic in self._icebergs.items()
                   if now - ic.last_renewed > self.cfg.iceberg_timeout_sec]
        for k in expired:
            if self._icebergs[k].confirmed:
                logger.info(f"Iceberg EXPIROU: {self._icebergs[k].broker} "
                            f"@ {self._icebergs[k].price} "
                            f"({self._icebergs[k].renewals} renovações, "
                            f"{self._icebergs[k].total_vol:,} vol total)")
            del self._icebergs[k]

        if key in self._icebergs:
            ic = self._icebergs[key]
            # Verificar se o lote está dentro da tolerância
            variation = abs(tick.qty - ic.ref_qty) / max(ic.ref_qty, 1) * 100
            if variation <= self.cfg.iceberg_lot_tolerance:
                ic.renewals    += 1
                ic.total_vol   += tick.qty
                ic.last_renewed = now
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
                first_seen=now, last_renewed=now
            )

    # ──────────────────────────────────────────────────────────
    # DETECÇÃO DE BEST OFFER PASSIVO
    # ──────────────────────────────────────────────────────────

    def _update_best_offer_log(self):
        """Registra quem está no 1º nível do book, separando ask (venda) e bid (compra)."""
        now = time.time()

        # Best ask (venda) → log exclusivo do lado vendedor
        if self._book_sell:
            best_sell_price = min(self._book_sell.keys())
            lvl = self._book_sell[best_sell_price]
            self._best_ask_log[lvl.broker].append(now)

        # Best bid (compra) → log exclusivo do lado comprador
        if self._book_buy:
            best_buy_price = max(self._book_buy.keys())
            lvl = self._book_buy[best_buy_price]
            self._best_bid_log[lvl.broker].append(now)

    def _count_best_level_brokers(self, log: dict) -> dict:
        """Conta presenças recentes de cada broker em um nível. {broker: count}"""
        now = time.time()
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

    def _register_price_touch(self, price: float):
        price_r = round(price, 2)
        self._price_touches[price_r].append(time.time())

    def _get_absorbed_levels(self) -> list[tuple]:
        """
        Retorna níveis de preço que foram tocados >= min_touches
        na janela de absorção. Indica defesa de região.
        """
        now = time.time()
        cutoff = now - self.cfg.absorption_window_sec
        levels = []
        for price, touches in self._price_touches.items():
            recent = [t for t in touches if t >= cutoff]
            if len(recent) >= self.cfg.absorption_min_touches:
                levels.append((price, len(recent)))
        return sorted(levels, key=lambda x: -x[1])

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
        now = time.time()
        cutoff = now - self.cfg.urgency_window_sec
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
        now = time.time()
        cutoff = now - self.cfg.flow_window_sec

        vol_buy  = 0
        vol_sell = 0

        for tick in reversed(self._ticks):
            if tick.timestamp < cutoff:
                break
            # Dar peso 2x para corretoras de alta relevância
            weight = 2 if tick.broker.upper() in [b.upper() for b in self.cfg.high_relevance_brokers] else 1
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
        confirmed_icebergs = [(k, ic) for k, ic in self._icebergs.items() if ic.confirmed]

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
        for (broker, side, price), ic in confirmed_icebergs:
            # ── Metodologia Sociedade dos Traders:
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
                        "reason":     f"Iceberg COMPRADOR de {broker} @ {price:.2f} | "
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
                        "reason":     f"Iceberg VENDEDOR de {broker} @ {price:.2f} | "
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
            top_level, touches = absorbed_levels[0]
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
                    "reason":     f"Absorção @ {top_level:.2f} ({touches} toques) | "
                                  f"Preço rompeu para {last_price:.2f} | Fluxo: {pct_buy:.1f}%"
                })
            elif flow_side == Side.SELL and last_price < top_level:
                sell_candidates.append({
                    "pattern":    PatternType.ABSORPTION,
                    "broker":     "Detectado por nível",
                    "price":      last_price,
                    "stop_price": round(top_level + self.cfg.stop_ticks_behind * self.cfg.tick_size, 2),
                    "confidence": conf,
                    "reason":     f"Absorção @ {top_level:.2f} ({touches} toques) | "
                                  f"Preço rompeu para {last_price:.2f} | Fluxo: {pct_sell:.1f}%"
                })

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
                reason=f"Aguardando setup | Fluxo: {pct_buy:.1f}% compra / {pct_sell:.1f}% venda"
            )

    def _calc_confidence(self, ic: IcebergCandidate, flow_pct: float,
                          best_offer: dict, urgent: list) -> float:
        """Calcula confiança do sinal (0.0 a 1.0)."""
        conf = 0.0

        # Base: renovações do iceberg
        conf += min(0.40, ic.renewals / self.cfg.iceberg_min_renewals * 0.25)

        # Força do fluxo
        conf += min(0.25, (flow_pct - self.cfg.flow_pct_threshold) / 35 * 0.25)

        # Broker relevante
        if ic.broker.upper() in [b.upper() for b in self.cfg.high_relevance_brokers]:
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
            reason=best["reason"]
        )

    # ──────────────────────────────────────────────────────────
    # API PÚBLICA
    # ──────────────────────────────────────────────────────────

    def get_signal(self) -> FlowSignal:
        with self._lock:
            return self._current_signal

    def get_state(self) -> dict:
        """Retorna estado completo do motor para debug/dashboard."""
        with self._lock:
            pct_buy, pct_sell = self._calc_flow_pressure()
            confirmed = [
                {"broker": ic.broker, "side": ic.side.value, "price": ic.price,
                 "renewals": ic.renewals, "total_vol": ic.total_vol}
                for _, ic in self._icebergs.items() if ic.confirmed
            ]
            absorbed = [{"price": p, "touches": t} for p, t in self._get_absorbed_levels()[:3]]
            urgent   = [{"broker": b, "side": s.value, "levels": n}
                        for b, s, n in self._get_urgent_brokers()]
            return {
                "asset":              self.asset,
                "tick_count":         len(self._ticks),
                "flow_pct_buy":       round(pct_buy, 1),
                "flow_pct_sell":      round(pct_sell, 1),
                "icebergs_confirmed": confirmed,
                "absorbed_levels":    absorbed,
                "urgent_brokers":     urgent,
                "best_ask_brokers":   list(self._get_best_ask_brokers().keys()),
                "best_bid_brokers":   list(self._get_best_bid_brokers().keys()),
                "signal":             self._current_signal.to_dict(),
            }

    def reset(self):
        """Reset completo do estado (início de novo dia)."""
        with self._lock:
            self._ticks.clear()
            self._book_buy.clear()
            self._book_sell.clear()
            self._icebergs.clear()
            self._best_ask_log.clear()
            self._best_bid_log.clear()
            self._price_touches.clear()
            self._urgency_log.clear()
            self._current_signal = FlowSignal(
                signal=Signal.WAIT, pattern=PatternType.NONE,
                direction=Side.NONE, price=0.0, stop_price=0.0,
                broker="", confidence=0.0, reason="Reset diário"
            )
        logger.info(f"Motor resetado para {self.asset}")
