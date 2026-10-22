"""
RADAR DE FLUXO — icebergs de todas as ações
===========================================
Um DefesaDetector por papel (criado no primeiro negócio dele). O giro do iceberg é a
corretora repondo o lote no mesmo preço (on_renovacao), não cada agressão. Cada iceberg
confirmado vira um registro do dia, atualizado pelos eventos do detector: segurou
(4 ticks a favor), rompida, virou sniper. Spec: docs/superpowers/specs/2026-10-17-radar-design.md.

HISTÓRICO: com `pasta_persistencia`, cada registro (segurando, seguraram, romperam, viraram sniper) é gravado em
`radar_AAAA-MM-DD.jsonl` (um por dia da B3; linha = registro inteiro, vale a última de cada id) e recarregado por
`carregar()` ao subir. Só o REGISTRO (giros, volume, horários), não os negócios. Um registro que estava "segurando"
quando o servidor caiu volta como "interrompido": o detector vivo se perdeu e o desfecho não é conhecido.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from core import calibracao
from core.defesas import DefesaDetector

logger = logging.getLogger("Radar")

FUSO_B3 = timezone(timedelta(hours=-3))
LIMITE_LISTA = 300          # exibição; não é regra de mercado
INTERVALO_SALVAR = 5.0      # s entre gravações do histórico (técnico; não é regra de mercado)


def _dia(ts: float):
    return datetime.fromtimestamp(ts, FUSO_B3).date()


class Radar:
    def __init__(self, cfg, calibracao_tabela: dict | None = None, pasta_persistencia: str | None = None):
        self.cfg = cfg
        self._pasta = pasta_persistencia
        self._t_salvo = 0.0
        self._tabela = calibracao.carregar() if calibracao_tabela is None else calibracao_tabela
        self.reset()

    def reset(self):
        if getattr(self, "_registros", None):
            self.salvar()                # fecha o dia anterior no arquivo dele antes de zerar
        self._salvo: dict = {}           # id → última linha gravada (só grava o que mudou)
        self._detectores: dict = {}      # papel → DefesaDetector
        self._registros: dict = {}       # id → registro (um por iceberg confirmado, mesmo no mesmo nível)
        self._atual: dict = {}           # (papel, corretora, lado, nível) → id do registro da defesa atual
        self._chave_de: dict = {}        # id → (papel, corretora, lado, nível)
        self._vivos: dict = {}           # (papel, corretora, lado, nível) → Defesa que o detector acompanha
        self._seq = 0
        self._negocios = 0
        self._dia = None
        self._agora = 0.0                # maior hora vista (negócio ou giro): o "agora" da janela de 2/5 min

    # ── entrada
    def on_tick(self, tick):
        dia = _dia(tick.timestamp)
        if self._dia is not None and dia != self._dia:
            self.reset()
        self._dia = dia
        self._agora = max(self._agora, tick.timestamp)
        ativo = tick.asset
        self._negocios += 1
        self._detector(ativo).on_tick(tick)
        self._talvez_salvar()

    def _detector(self, ativo: str):
        det = self._detectores.get(ativo)
        if det is None:
            det = DefesaDetector(self.cfg)
            det.ao_evento = lambda ev, d, ativo=ativo: self._ao_evento(ativo, ev, d)
            det.escrever_log = False      # com ~650 papéis inundaria o log; os eventos ficam na lista
            self._detectores[ativo] = det
        return det

    def on_renovacao(self, ativo: str, corretora: str, lado: str, preco: float, ts: float) -> None:
        """Giro vindo do livro de ofertas: a corretora repôs o lote neste preço."""
        if not ativo:
            return
        dia = _dia(ts)
        if self._dia is not None and dia != self._dia:
            self.reset()
        self._dia = dia
        self._agora = max(self._agora, ts)
        self._detector(ativo).on_renovacao(corretora, lado, preco, ts)
        self._talvez_salvar()

    # ── histórico em disco
    def _arquivo(self, dia) -> str:
        return os.path.join(self._pasta, f"radar_{dia.isoformat()}.jsonl")

    def _talvez_salvar(self) -> None:
        if self._pasta and time.monotonic() - self._t_salvo >= INTERVALO_SALVAR:
            self._t_salvo = time.monotonic()
            self.salvar()

    def salvar(self) -> int:
        """Grava no arquivo do dia os registros que mudaram desde a última gravação; devolve quantos."""
        if not self._pasta or self._dia is None:
            return 0
        try:
            linhas = []
            for idreg, reg in self._registros.items():
                self._atualizar(idreg, reg)
                linha = json.dumps({"id": idreg, **reg}, ensure_ascii=False, sort_keys=True)
                if self._salvo.get(idreg) != linha:
                    linhas.append(linha)
                    self._salvo[idreg] = linha
            if linhas:
                os.makedirs(self._pasta, exist_ok=True)
                with open(self._arquivo(self._dia), "a", encoding="utf-8") as f:
                    f.write("\n".join(linhas) + "\n")
            return len(linhas)
        except Exception:
            logger.exception("Radar: falha ao gravar o histórico em %s", self._pasta)
            return 0

    def carregar(self, dia=None) -> int:
        """Recarrega os registros do dia (hoje na B3, ou `dia`) gravados antes; devolve quantos."""
        if not self._pasta:
            return 0
        dia = dia or _dia(time.time())
        arq = self._arquivo(dia)
        if not os.path.exists(arq):
            return 0
        ultimos: dict = {}
        try:
            with open(arq, encoding="utf-8") as f:
                for linha in f:
                    linha = linha.strip()
                    if not linha:
                        continue
                    try:
                        d = json.loads(linha)
                        ultimos[int(d.pop("id"))] = d
                    except (ValueError, KeyError, TypeError):
                        continue                 # linha cortada (queda no meio da escrita): ignora
        except OSError:
            logger.exception("Radar: falha ao ler o histórico %s", arq)
            return 0
        for idreg in sorted(ultimos):
            reg = ultimos[idreg]
            self._registros[idreg] = reg
            self._chave_de[idreg] = (reg["ativo"], reg["corretora"], reg["lado"], ("restaurado", idreg))
            self._salvo[idreg] = json.dumps({"id": idreg, **reg}, ensure_ascii=False, sort_keys=True)
            if reg.get("situacao") == "segurando":
                reg["situacao"] = "interrompido"        # o detector vivo se perdeu: o desfecho é desconhecido
            self._agora = max(self._agora, reg.get("ultimo_giro_as") or 0, reg.get("confirmado_as") or 0)
        if ultimos:
            self._seq = max(ultimos)
            self._dia = dia
        return len(ultimos)

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
                "ultimo_giro_as": d.ultimo_giro or None,
                "situacao": "segurando", "desfecho_as": None, "segurou_as": None, "rompeu_as": None,
            }
            self._atual[chave], self._chave_de[self._seq] = self._seq, chave
            self._vivos[chave] = d
            return
        if self._vivos.get(chave) is not d or chave not in self._atual:
            return                       # evento de outra defesa (ex.: candidata nova no mesmo nível)
        reg = self._registros[self._atual[chave]]
        reg["giros"], reg["volume"] = d.giros, d.vol_passivo
        reg["ultimo_giro_as"] = d.ultimo_giro or None
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
            reg["ultimo_giro_as"] = d.ultimo_giro or None

    def lista(self, situacao: str | None = None, limite: int = LIMITE_LISTA,
              janela: float | None = None, ordem: str = "padrao") -> list[dict]:
        """`janela` (s): só os icebergs com giro nos últimos `janela` segundos (2 ou 5 min: ESCOLHA DE TELA nossa, não vem das aulas),
        do giro mais recente para o mais antigo. `ordem="giros"`: agrupa as corretoras do mesmo papel, lado e
        preço (várias corretoras defendendo o mesmo nível ficam juntas); os grupos vão do maior para o menor
        número de giros (o do grupo é o da corretora com mais giros; empate: maior volume somado) e, dentro do
        grupo, a corretora com mais giros vem primeiro. Vale sobre a lista inteira, antes do corte por `limite`.
        Ordem e agrupamento também são escolha de exibição, não regra de mercado do professor."""
        segurando, resolvidos = [], []
        for idreg, reg in self._registros.items():
            self._atualizar(idreg, reg)
            if situacao and reg["situacao"] != situacao:
                continue
            if janela and not (reg.get("ultimo_giro_as") and reg["ultimo_giro_as"] >= self._agora - janela):
                continue
            (segurando if reg["situacao"] == "segurando" else resolvidos).append(reg)
        segurando.sort(key=lambda r: -r["volume"])
        resolvidos.sort(key=lambda r: -(r["desfecho_as"] or 0))
        saida = []
        todos = segurando + resolvidos
        if ordem == "giros":
            grupos: dict = {}
            for r in todos:
                grupos.setdefault((r["ativo"], r["lado"], r["preco"]), []).append(r)
            for membros in grupos.values():
                membros.sort(key=lambda r: (-r["giros"], -r["volume"]))
            todos = [r for membros in sorted(
                grupos.values(), key=lambda m: (-m[0]["giros"], -sum(r["volume"] for r in m), m[0]["ativo"]))
                for r in membros]
        elif janela:
            todos.sort(key=lambda r: -r["ultimo_giro_as"])
        anterior = None
        for reg in todos[:limite]:
            r = dict(reg)
            if ordem == "giros":
                grupo = (reg["ativo"], reg["lado"], reg["preco"])
                r["grupo_inicio"] = grupo != anterior       # 1ª linha do grupo: a tela separa os grupos
                anterior = grupo
            r["acerto"] = calibracao.acerto_iceberg(self._tabela, r["ativo"], r["volume"])
            saida.append(r)
        return saida

    def resumo(self) -> dict:
        cont = {"segurando": 0, "segurou": 0, "rompeu": 0, "virou sniper": 0, "interrompido": 0}
        for reg in self._registros.values():
            cont[reg["situacao"]] += 1
        res = {"segurando": cont["segurando"], "seguraram": cont["segurou"], "romperam": cont["rompeu"],
               "viraram_sniper": cont["virou sniper"], "papeis": len(self._detectores),
               "negocios": self._negocios}
        if cont["interrompido"]:
            res["interrompidos"] = cont["interrompido"]    # restaurados do arquivo, sem desfecho conhecido
        return res
