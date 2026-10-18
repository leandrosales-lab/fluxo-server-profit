"""
RADAR DE FLUXO — icebergs de todas as ações
===========================================
Um DefesaDetector por papel (criado no primeiro negócio dele). Cada iceberg confirmado vira um
registro do dia, atualizado pelos eventos do detector: segurou (4 ticks a favor), rompida, virou
sniper. Spec: docs/superpowers/specs/2026-10-17-radar-design.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core import calibracao
from core.defesas import DefesaDetector

FUSO_B3 = timezone(timedelta(hours=-3))
LIMITE_LISTA = 300          # exibição; não é regra de mercado


def _dia(ts: float):
    return datetime.fromtimestamp(ts, FUSO_B3).date()


class Radar:
    def __init__(self, cfg, calibracao_tabela: dict | None = None):
        self.cfg = cfg
        self._tabela = calibracao.carregar() if calibracao_tabela is None else calibracao_tabela
        self.reset()

    def reset(self):
        self._detectores: dict = {}      # papel → DefesaDetector
        self._registros: dict = {}       # id → registro (um por iceberg confirmado, mesmo no mesmo nível)
        self._atual: dict = {}           # (papel, corretora, lado, nível) → id do registro da defesa atual
        self._chave_de: dict = {}        # id → (papel, corretora, lado, nível)
        self._vivos: dict = {}           # (papel, corretora, lado, nível) → Defesa que o detector acompanha
        self._seq = 0
        self._negocios = 0
        self._dia = None

    # ── entrada
    def on_tick(self, tick):
        dia = _dia(tick.timestamp)
        if self._dia is not None and dia != self._dia:
            self.reset()
        self._dia = dia
        ativo = tick.asset
        det = self._detectores.get(ativo)
        if det is None:
            det = DefesaDetector(self.cfg)
            det.ao_evento = lambda ev, d, ativo=ativo: self._ao_evento(ativo, ev, d)
            det.escrever_log = False      # com ~650 papéis inundaria o log; os eventos ficam na lista
            self._detectores[ativo] = det
        self._negocios += 1
        det.on_tick(tick)

    def envolver(self, add_tick, engine):
        """Entrega todo negócio ao radar e só o do papel aberto (engine.asset) ao motor."""
        def entregar(tick):
            # Sob o lock do engine: o GET /api/radar lê o radar com ele, e a troca de papel
            # (POST /operar/ativo) não pode acontecer entre a comparação e a entrega ao motor
            with engine._lock:
                if not tick.asset:
                    tick.asset = engine.asset
                self.on_tick(tick)
                if tick.asset == engine.asset:
                    add_tick(tick)
        return entregar

    # ── eventos do detector
    def _ao_evento(self, ativo, ev, d):
        chave = (ativo, d.corretora, d.lado, d.nivel)
        if ev.evento == "confirmada" and d.tipo == "iceberg":
            if self._vivos.get(chave) is d:
                return
            self._seq += 1
            self._registros[self._seq] = {
                "ativo": ativo, "corretora": d.corretora, "lado": d.lado, "preco": d.preco,
                "giros": d.giros, "volume": d.vol_passivo, "confirmado_as": ev.ts,
                "situacao": "segurando", "desfecho_as": None, "segurou_as": None, "rompeu_as": None,
            }
            self._atual[chave], self._chave_de[self._seq] = self._seq, chave
            self._vivos[chave] = d
            return
        if self._vivos.get(chave) is not d or chave not in self._atual:
            return                       # evento de outra defesa (ex.: candidata nova no mesmo nível)
        reg = self._registros[self._atual[chave]]
        reg["giros"], reg["volume"] = d.giros, d.vol_passivo
        if ev.evento == "segurou":
            reg["segurou_as"] = ev.ts
            if reg["situacao"] == "segurando":
                reg["situacao"], reg["desfecho_as"] = "segurou", ev.ts
        elif ev.evento == "rompida":
            reg["rompeu_as"] = ev.ts
            if reg["situacao"] == "segurando":
                reg["situacao"], reg["desfecho_as"] = "rompeu", ev.ts
        elif ev.evento == "reclassificada" and d.tipo == "sniper":
            reg["situacao"], reg["desfecho_as"] = "virou sniper", ev.ts
            self._vivos.pop(chave, None)

    # ── consultas
    def _atualizar(self, idreg, reg):
        chave = self._chave_de[idreg]
        d = self._vivos.get(chave)
        if d is not None and self._atual.get(chave) == idreg:
            reg["giros"], reg["volume"] = d.giros, d.vol_passivo

    def lista(self, situacao: str | None = None, limite: int = LIMITE_LISTA) -> list[dict]:
        segurando, resolvidos = [], []
        for idreg, reg in self._registros.items():
            self._atualizar(idreg, reg)
            if situacao and reg["situacao"] != situacao:
                continue
            (segurando if reg["situacao"] == "segurando" else resolvidos).append(reg)
        segurando.sort(key=lambda r: -r["volume"])
        resolvidos.sort(key=lambda r: -(r["desfecho_as"] or 0))
        saida = []
        for reg in (segurando + resolvidos)[:limite]:
            r = dict(reg)
            r["acerto"] = calibracao.acerto_iceberg(self._tabela, r["ativo"], r["volume"])
            saida.append(r)
        return saida

    def resumo(self) -> dict:
        cont = {"segurando": 0, "segurou": 0, "rompeu": 0, "virou sniper": 0}
        for reg in self._registros.values():
            cont[reg["situacao"]] += 1
        return {"segurando": cont["segurando"], "seguraram": cont["segurou"], "romperam": cont["rompeu"],
                "viraram_sniper": cont["virou sniper"], "papeis": len(self._detectores),
                "negocios": self._negocios}
