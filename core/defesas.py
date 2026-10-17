"""
DEFESAS — quem está segurando um preço
======================================
Iceberg, sniper, fantasma e E2 pelas regras do professor. Spec:
docs/superpowers/specs/2026-10-17-defesas-design.md. Cada número vem do
EngineConfig (prefixo defesa_), com a aula de origem no comentário.

Este módulo não importa o engine: lê do Tick só timestamp, price, qty,
broker, side.value ("compra"/"venda"/"neutro") e passive_broker.
"""

from __future__ import annotations

from dataclasses import dataclass

COMPRA, VENDA = "compra", "venda"


def oposto(lado: str) -> str:
    return VENDA if lado == COMPRA else COMPRA


def chave_ordem(tick) -> tuple:
    """Ordem original: mesma corretora agressora, mesmo lado, mesmo ms (aula 9393818, 9 de 10 ordens)."""
    return (round(tick.timestamp * 1000), tick.broker, tick.side.value)


@dataclass
class OrdemOriginal:
    ms: int
    corretora: str
    lado: str
    qtd: int
    preco_ini: float
    preco_fim: float
    pedacos: int


def juntar_ordens(ticks) -> list:
    """Agrupa os negócios em ordens originais, na ordem em que cada ordem começou."""
    ordens: dict = {}
    for t in ticks:
        if t.side.value not in (COMPRA, VENDA):
            continue
        k = chave_ordem(t)
        o = ordens.get(k)
        if o is None:
            ordens[k] = OrdemOriginal(k[0], t.broker, k[2], t.qty, t.price, t.price, 1)
        else:
            o.qtd += t.qty
            o.preco_fim = t.price
            o.pedacos += 1
    return list(ordens.values())
