"""
Histórico do dia do papel aberto
================================
Ao abrir um papel (ou subir o servidor), o gráfico precisa começar no início do pregão e não na hora em
que o servidor conectou. A DLL baixa os negócios de hoje; este portão segura os negócios ao vivo do papel
aberto enquanto isso, entrega o histórico ao motor na ordem do relógio e depois solta os ao vivo que ainda
não estavam no histórico (a janela do download e a do ao vivo se sobrepõem por alguns segundos).

O histórico vai direto ao motor: não passa pelo radar (que já viu esses negócios ao vivo desde que o
servidor subiu) nem pelo gravador de CSV.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from core.engine import Tick

logger = logging.getLogger("Historico")

TIMEOUT_PADRAO = 120.0      # s: se o download não terminar, solta os negócios ao vivo e segue sem histórico


def _chave(t: Tick) -> tuple:
    return (t.price, t.qty, t.broker, t.side, t.passive_broker)


class PortaoHistorico:
    def __init__(self, engine, entrega_direta: Optional[Callable[[Tick], None]] = None,
                 timeout: float = TIMEOUT_PADRAO, relogio: Callable[[], float] = time.monotonic):
        self.engine = engine
        self.timeout = timeout
        self._relogio = relogio
        # add_tick puro do motor (sem radar nem gravador): é por onde o histórico entra
        self._direto = entrega_direta or engine.add_tick
        self._ao_vivo_add = self._direto       # add_tick do ao vivo (com o gravador); envolver() troca
        self._trava = threading.RLock()
        self._ativo = ""
        self._carregando = False
        self._inicio = 0.0
        self._historico: list[Tick] = []
        self._ao_vivo: list[Tick] = []

    # ── estado (GET /state)
    def estado(self) -> dict:
        with self._trava:
            return {"ativo": self._ativo, "carregando": self._carregando,
                    "recebidos": len(self._historico), "retidos": len(self._ao_vivo)}

    # ── controle
    def abrir(self, ativo: str) -> None:
        """Começa a segurar os negócios ao vivo de `ativo` até o histórico terminar."""
        with self._trava:
            self._ativo = ativo
            self._carregando = True
            self._inicio = self._relogio()
            self._historico = []
            self._ao_vivo = []

    def cancelar(self) -> None:
        """Sem histórico (DLL fora do ar): solta o que estava retido e segue ao vivo."""
        with self._trava:
            pronto = self._soltar([])
        self._entregar(*pronto)

    # ── entradas
    def envolver(self, add_tick: Callable[[Tick], None]) -> Callable[[Tick], None]:
        """add_tick do motor com o portão na frente: retém o ao vivo do papel aberto enquanto carrega."""
        self._ao_vivo_add = add_tick

        def entregar(tick: Tick) -> None:
            pronto = ([], [])
            with self._trava:
                if self._carregando and tick.asset in ("", self._ativo):
                    if self._relogio() - self._inicio > self.timeout:
                        logger.warning(f"Histórico de {self._ativo} não terminou em {self.timeout:.0f}s "
                                       f"- seguindo só ao vivo")
                        pronto = self._soltar([])
                    else:
                        self._ao_vivo.append(tick)
                        return
            self._entregar(*pronto)     # fora do lock do portão: o motor tem o dele (e o radar pega os dois)
            add_tick(tick)
        return entregar

    def historico(self, ativo: str, ticks: list) -> None:
        """Pedaço do histórico (cronológico)."""
        with self._trava:
            if self._carregando and ativo == self._ativo:
                self._historico.extend(ticks)

    def fim(self, ativo: str, n: int = 0) -> None:
        with self._trava:
            if not (self._carregando and ativo == self._ativo):
                return
            pronto = self._soltar(sorted(self._historico, key=lambda t: t.timestamp))
        self._entregar(*pronto)

    # ── interno
    def _soltar(self, historico: list) -> tuple[list, list]:
        """Fecha o portão (sob o lock) e devolve (histórico, ao vivo retido) para entregar ao motor."""
        ao_vivo, self._ao_vivo = self._ao_vivo, []
        self._historico = []
        self._carregando = False
        if historico:
            ultimo = historico[-1].timestamp
            no_ultimo = {_chave(t) for t in historico if t.timestamp == ultimo}
            ao_vivo = [t for t in ao_vivo
                       if t.timestamp > ultimo or (t.timestamp == ultimo and _chave(t) not in no_ultimo)]
            logger.info(f"Histórico de {self._ativo}: {len(historico)} negócios do dia + "
                        f"{len(ao_vivo)} ao vivo que chegaram durante o download")
        for t in historico:
            if not t.asset:
                t.asset = self._ativo
        return historico, ao_vivo

    def _entregar(self, historico: list, ao_vivo: list) -> None:
        for t in historico:        # direto: sem radar (já viu ao vivo) e sem gravador
            self._direto(t)
        for t in ao_vivo:          # pelo caminho normal do ao vivo (o gravador também grava)
            self._ao_vivo_add(t)
