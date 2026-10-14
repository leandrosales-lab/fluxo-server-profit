"""
INFERÊNCIA DE NEGÓCIOS A PARTIR DO RTD
=======================================
O RTD do Profit não entrega o Times & Trades: entrega um retrato do
ativo a cada atualização (último preço, volume e nº de negócios
ACUMULADOS no dia, agentes do último negócio e, opcionalmente, o
melhor bid/ask). Este módulo reconstrói ticks a partir desses retratos:

  - Quantidade: diferença do volume acumulado entre dois retratos
  - Lado agressor:
      1. Regra da cotação (se bid/ask disponíveis): compara o preço com
         o bid/ask ANTERIOR ao negócio (no ask = compra, no bid = venda,
         dentro do spread = lado mais próximo)
      2. Regra do tick: preço subiu = compra, caiu = venda,
         igual = mesmo lado do negócio anterior
  - Corretora: a agressora (ACP se compra, AVD se venda); a passiva é a
    outra ponta (AVD numa compra, ACP numa venda)

Limitação: se vários negócios acontecerem entre dois retratos, eles
viram um único tick agregado (contado em `aggregated_trades`).
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional

from core.engine import Tick, Side

logger = logging.getLogger("RTD")


@dataclass
class RTDSnapshot:
    price:     float            # ULT — último preço
    volume:    float            # QTT — quantidade acumulada no dia (VOL do Profit é R$, não serve)
    trades:    int              # NEG — nº de negócios acumulado no dia
    buyer:     str = ""         # ACP — agente comprador do último negócio
    seller:    str = ""         # AVD — agente vendedor do último negócio
    bid:       float = 0.0      # melhor oferta de compra (opcional)
    ask:       float = 0.0      # melhor oferta de venda (opcional)
    timestamp: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> "RTDSnapshot":
        return cls(
            price     = float(d["price"]),
            volume    = float(d["volume"]),
            trades    = int(float(d.get("trades", 0))),
            buyer     = str(d.get("buyer", "")).strip().upper(),
            seller    = str(d.get("seller", "")).strip().upper(),
            bid       = float(d.get("bid") or 0),
            ask       = float(d.get("ask") or 0),
            timestamp = float(d.get("timestamp") or time.time()),
        )


class RTDTradeInferer:
    """Converte retratos sucessivos do RTD em ticks com lado agressor."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._prev: Optional[RTDSnapshot] = None
        self._last_diff_price: float = 0.0   # último preço diferente (regra do tick)
        self._last_side: Side = Side.NONE
        self.ticks_emitted = 0
        self.aggregated_trades = 0           # negócios que chegaram agrupados
        self.side_by_quote = 0
        self.side_by_tick = 0
        self.undetermined = 0

    def update(self, snap: RTDSnapshot) -> Optional[Tick]:
        """Processa um retrato. Retorna o Tick inferido ou None."""
        prev = self._prev
        if snap.price <= 0:
            return None

        # Primeiro retrato ou virada de dia (acumulados zeraram): só baseline
        if prev is None or snap.volume < prev.volume or snap.trades < prev.trades:
            self._prev = snap
            self._last_diff_price = snap.price
            self._last_side = Side.NONE
            return None

        qty = int(round(snap.volume - prev.volume))
        new_trades = snap.trades - prev.trades
        if qty <= 0:
            # Sem negócio novo — só atualiza o book para a regra da cotação
            self._prev = snap
            return None

        side = self._side_by_quote(snap.price, prev.bid, prev.ask)
        if side != Side.NONE:
            self.side_by_quote += 1
        else:
            side = self._side_by_tick(snap.price)
            if side != Side.NONE:
                self.side_by_tick += 1

        if snap.price != self._last_diff_price:
            self._last_diff_price = snap.price
        self._prev = snap

        if side == Side.NONE:
            self.undetermined += 1
            return None
        self._last_side = side

        if new_trades > 1:
            self.aggregated_trades += new_trades - 1
        self.ticks_emitted += 1

        broker  = snap.buyer if side == Side.BUY else snap.seller
        passiva = snap.seller if side == Side.BUY else snap.buyer
        return Tick(
            timestamp = snap.timestamp,
            price     = snap.price,
            qty       = qty,
            broker    = broker or "DESCONHECIDA",
            side      = side,
            passive_broker = passiva,   # "" se o RTD não trouxe o agente
        )

    @staticmethod
    def _side_by_quote(price: float, bid: float, ask: float) -> Side:
        if bid <= 0 or ask <= 0 or ask < bid:
            return Side.NONE
        if price >= ask:
            return Side.BUY
        if price <= bid:
            return Side.SELL
        mid = (bid + ask) / 2
        if price > mid:
            return Side.BUY
        if price < mid:
            return Side.SELL
        return Side.NONE

    def _side_by_tick(self, price: float) -> Side:
        if price > self._last_diff_price:
            return Side.BUY
        if price < self._last_diff_price:
            return Side.SELL
        return self._last_side   # zero-tick: mantém o lado anterior

    def stats(self) -> dict:
        return {
            "ticks_emitted":     self.ticks_emitted,
            "aggregated_trades": self.aggregated_trades,
            "side_by_quote":     self.side_by_quote,
            "side_by_tick":      self.side_by_tick,
            "undetermined":      self.undetermined,
        }
