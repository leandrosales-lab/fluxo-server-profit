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

import bisect
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("Defesas")

COMPRA, VENDA = "compra", "venda"
EVENTOS_GUARDADOS = 200      # memória para a tela e o estado; não é regra de mercado


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


def _fmt(preco: float) -> str:
    return f"{preco:.2f}".replace(".", ",")


@dataclass
class Defesa:
    """Uma candidata/defesa: (corretora, lado defendido, nível). Lado defendido "compra" = suporte
    (a corretora segura a venda agressora); "venda" = resistência."""
    corretora: str
    lado: str
    nivel: int
    preco: float
    desde: float
    ultima: float
    vol_nivel_inicio: int = 0      # volume agredido contra o lado no nível quando nasceu (fatia)
    tipo: str = ""                 # "" | iceberg | sniper | fantasma
    estado: str = "candidata"      # candidata | alerta | confirmada | rompida
    vol_passivo: int = 0
    giros: int = 0                 # ordens originais executadas contra ela no preço
    vol_agredido: int = 0
    agressoes: int = 0             # ordens originais dela no preço, do lado defendido
    agressoes_vazio: int = 0       # agressões com o lado dela vazio no preço (fantasma)
    reacoes: int = 0               # absorve e boleta de volta em até defesa_reacao_ms
    alem_max: int = 0              # maior distância (ticks) de negócio além do nível
    alem_pendente: bool = False    # houve negócio além depois de ela ter absorvido
    defendeu_apos_alem: bool = False
    agressores: dict = field(default_factory=dict)   # agressores distintos (dict = ordem estável)
    niveis: list = field(default_factory=list)       # preços anteriores (mudou de nível)
    e2_com: str = ""
    fila_pendente: bool = False
    ordem_passiva: tuple = ()
    ordem_agressora: tuple = ()

    @property
    def ativa(self) -> bool:
        return self.estado == "confirmada"

    def to_dict(self) -> dict:
        return {"tipo": self.tipo, "estado": self.estado, "corretora": self.corretora, "lado": self.lado,
                "preco": self.preco, "desde": self.desde, "ultima": self.ultima,
                "vol_passivo": self.vol_passivo, "giros": self.giros, "vol_agredido": self.vol_agredido,
                "agressoes": self.agressoes, "reacoes": self.reacoes, "alem_max": self.alem_max,
                "niveis_anteriores": list(self.niveis), "e2_com": self.e2_com}


@dataclass
class EventoDefesa:
    ts: float
    evento: str      # alerta | confirmada | reclassificada | mudou_nivel | rompida | fila_formada |
                     # defensor_ausente | e2_formado | e2_uma_acabou
    tipo: str
    corretora: str
    lado: str
    preco: float
    detalhe: str = ""
    parceiro: str = ""

    def to_dict(self) -> dict:
        return {"ts": self.ts, "evento": self.evento, "tipo": self.tipo, "corretora": self.corretora,
                "lado": self.lado, "preco": self.preco, "detalhe": self.detalhe, "parceiro": self.parceiro}


@dataclass
class _Agressao:
    nivel: int
    ms: int
    corretora: str
    passiva: str


class DefesaDetector:
    """Classifica quem segura cada preço. Uma candidata por (corretora, lado defendido, nível)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self._defesas: dict = {}                                 # chave → Defesa
        self._confirmadas: dict = {}                             # chave → Defesa (estado confirmada)
        self._por_nivel = {COMPRA: defaultdict(dict), VENDA: defaultdict(dict)}   # lado → nível → {chave: None}
        self._niveis = {COMPRA: [], VENDA: []}                   # níveis com candidatas, ordenados
        self._vol_nivel: dict = defaultdict(int)                 # (lado defendido, nível) → volume contra
        self._ult_agr = {COMPRA: None, VENDA: None}              # última agressão de cada lado
        self._ult_outra = {COMPRA: None, VENDA: None}            # última de outra corretora que não a anterior
        self._eventos: deque = deque(maxlen=EVENTOS_GUARDADOS)

    # ── consultas ──────────────────────────────────────────────
    def ativas(self) -> list:
        return list(self._confirmadas.values())

    def eventos(self, n: int = 20) -> list:
        return list(self._eventos)[-n:]

    def nivel(self, preco: float) -> int:
        return round(preco / self.cfg.tick_size)

    def fatia(self, d: Defesa) -> float:
        total = self._vol_nivel[(d.lado, d.nivel)] - d.vol_nivel_inicio
        return d.vol_passivo / total if total > 0 else 1.0

    # ── entrada ────────────────────────────────────────────────
    def on_tick(self, tick) -> None:
        lado_agr = tick.side.value
        if lado_agr not in (COMPRA, VENDA):
            return
        n = self.nivel(tick.price)
        ts = tick.timestamp
        ordem = chave_ordem(tick)
        self._negocio_alem(n, ts)
        lado_pas = oposto(lado_agr)

        # Lado passivo: quem estava no book segurou a agressão
        if tick.passive_broker:
            d = self._obter(tick.passive_broker, lado_pas, n, tick.price, ts)
            d.vol_passivo += tick.qty
            if d.ordem_passiva != ordem:
                d.ordem_passiva = ordem
                d.giros += 1
            d.agressores[tick.broker] = None
            self._atividade(d, ts)
        self._vol_nivel[(lado_pas, n)] += tick.qty

        # Lado agressor: agredir no preço defende o lado dele naquele preço
        d = self._obter(tick.broker, lado_agr, n, tick.price, ts)
        d.vol_agredido += tick.qty
        if d.ordem_agressora != ordem:
            d.ordem_agressora = ordem
            d.agressoes += 1
            ult = self._ult_agr[lado_pas]
            if (ult is not None and ult.nivel == n and ult.corretora != tick.broker
                    and ordem[0] - ult.ms <= self.cfg.defesa_reacao_ms
                    and ult.passiva in ("", tick.broker)):
                d.reacoes += 1
            if self._lado_vazio(lado_agr, n, tick.broker):
                d.agressoes_vazio += 1
        self._atividade(d, ts)
        self._registrar_agressao(lado_agr, _Agressao(n, ordem[0], tick.broker, tick.passive_broker))

    # ── internos ───────────────────────────────────────────────
    def _registrar_agressao(self, lado: str, a: _Agressao):
        ult = self._ult_agr[lado]
        if ult is not None and ult.corretora != a.corretora:
            self._ult_outra[lado] = ult
        self._ult_agr[lado] = a

    def _ultima_de_outra(self, lado: str, corretora: str) -> Optional[_Agressao]:
        ult = self._ult_agr[lado]
        if ult is not None and ult.corretora != corretora:
            return ult
        outra = self._ult_outra[lado]
        return outra if outra is not None and outra.corretora != corretora else None

    def _lado_vazio(self, lado: str, n: int, corretora: str) -> bool:
        """Lado de quem agride vazio no preço (o "15 vazio", aula-02 25:09), pelos negócios:
        compra agressora executa na melhor venda, venda agressora na melhor compra (decisão 3 do plano)."""
        contra = self._ultima_de_outra(oposto(lado), corretora)
        if contra is None:
            return False
        vazio = contra.nivel < n if lado == COMPRA else contra.nivel > n
        mesma = self._ultima_de_outra(lado, corretora)
        return vazio and (mesma is None or mesma.nivel != n)

    def _obter(self, corretora: str, lado: str, n: int, preco: float, ts: float) -> Defesa:
        k = (corretora, lado, n)
        d = self._defesas.get(k)
        if d is None:
            d = Defesa(corretora, lado, n, round(preco, 2), ts, ts,
                       vol_nivel_inicio=self._vol_nivel[(lado, n)])
            self._defesas[k] = d
            if n not in self._por_nivel[lado]:
                bisect.insort(self._niveis[lado], n)
            self._por_nivel[lado][n][k] = None
        return d

    @staticmethod
    def _chave(d: Defesa) -> tuple:
        return (d.corretora, d.lado, d.nivel)

    def _remover(self, k: tuple):
        d = self._defesas.pop(k)
        self._confirmadas.pop(k, None)
        por = self._por_nivel[d.lado]
        por[d.nivel].pop(k, None)
        if not por[d.nivel]:
            del por[d.nivel]
            niveis = self._niveis[d.lado]
            del niveis[bisect.bisect_left(niveis, d.nivel)]

    def _atividade(self, d: Defesa, ts: float):
        d.ultima = ts
        if d.alem_pendente:
            d.alem_pendente = False
            d.defendeu_apos_alem = True
        self._classificar(d, ts)

    def _classificar(self, d: Defesa, ts: float):
        cfg = self.cfg
        if d.reacoes > 0 or d.defendeu_apos_alem:
            novo = "sniper"
        elif d.vol_passivo == 0 and d.agressoes_vazio >= cfg.defesa_fantasma_agressoes:
            novo = "fantasma"
        elif (d.giros >= cfg.defesa_iceberg_giros and d.vol_passivo >= cfg.defesa_iceberg_lote_min
              and d.alem_max == 0 and d.agressoes == 0):
            novo = "iceberg"
        else:
            if (d.estado == "candidata" and d.giros >= 1 and d.alem_max == 0
                    and d.vol_passivo >= cfg.defesa_iceberg_lote_min):
                d.estado = "alerta"
                self._evento("alerta", d, ts)
                self._formar_e2(d, ts)
            return
        if d.tipo == novo and d.ativa:
            return
        anterior = d.tipo
        d.tipo = novo
        d.estado = "confirmada"
        self._confirmadas[self._chave(d)] = d
        if anterior and anterior != novo:
            self._evento("reclassificada", d, ts, f"{anterior} → {novo}")
            self._mudar_nivel(d, ts)
        elif not self._mudar_nivel(d, ts):
            self._evento("confirmada", d, ts)
        self._formar_e2(d, ts)

    def _mudar_nivel(self, d: Defesa, ts: float) -> bool:
        """Mesma corretora passa a defender outro preço do mesmo lado: é a mesma defesa (aula 9393841)."""
        if d.tipo != "sniper":
            return False
        antigas = [o for o in self._confirmadas.values()
                   if o is not d and o.corretora == d.corretora and o.lado == d.lado and o.tipo == "sniper"]
        if not antigas:
            return False
        o = max(antigas, key=lambda x: x.ultima)
        d.niveis = o.niveis + [o.preco]
        d.desde = o.desde
        self._evento("mudou_nivel", d, ts, f"{_fmt(o.preco)} → {_fmt(d.preco)}")
        for a in antigas:
            self._desfazer_e2(a, ts)
            self._remover(self._chave(a))
        return True

    def _negocio_alem(self, n: int, ts: float):
        """Negócio além do nível: suporte (compra) abaixo dele, resistência (venda) acima."""
        compra, venda = self._niveis[COMPRA], self._niveis[VENDA]
        afetados = [(COMPRA, L) for L in compra[bisect.bisect_right(compra, n):]]
        afetados += [(VENDA, L) for L in venda[:bisect.bisect_left(venda, n)]]
        for lado, L in afetados:
            dist = abs(L - n)
            for k in list(self._por_nivel[lado].get(L, {})):
                d = self._defesas[k]
                d.alem_max = max(d.alem_max, dist)
                if d.estado in ("alerta", "confirmada", "rompida") and d.vol_passivo > 0:
                    d.alem_pendente = True
                if d.tipo == "iceberg" and d.estado == "confirmada":
                    d.estado = "rompida"
                    self._confirmadas.pop(k, None)
                    self._evento("rompida", d, ts, f"negócio a {dist} tick(s) além")
                    self._desfazer_e2(d, ts)
                if dist >= self.cfg.defesa_ausente_ticks:
                    if d.ativa:
                        self._evento("defensor_ausente", d, ts, f"negócio a {dist} ticks além")
                        self._desfazer_e2(d, ts)
                    self._remover(k)

    def _formar_e2(self, d: Defesa, ts: float):
        """E2 — completado na Tarefa 3."""

    def _desfazer_e2(self, d: Defesa, ts: float):
        """E2 — completado na Tarefa 3."""

    def _evento(self, evento: str, d: Defesa, ts: float, detalhe: str = "", parceiro: str = ""):
        self._eventos.append(EventoDefesa(ts, evento, d.tipo, d.corretora, d.lado, d.preco, detalhe, parceiro))
        nivel_log = logging.DEBUG if evento == "alerta" else logging.INFO
        logger.log(nivel_log, f"Defesa {d.tipo or 'candidata'} {d.corretora} {d.lado} @ {_fmt(d.preco)}: "
                              f"{evento}" + (f" ({detalhe})" if detalhe else ""))
