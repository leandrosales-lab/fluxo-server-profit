"""
LOG EM MEMÓRIA PARA A TELA CONEXÃO (GET /log)
=============================================
Um logging.Handler que guarda os últimos N registros (INFO ou mais) num deque,
thread-safe. Instalado no logger raiz pelo FlowServer, capta ProfitDLL,
ProfitDLLHistorico, API, Main etc.

Antes de guardar, troca por "•••" qualquer trecho igual ao valor atual de
PROFITDLL_KEY, PROFITDLL_USER ou PROFITDLL_PASS: credencial nunca sai do servidor.
"""
import os
import logging
import threading
from collections import deque
from typing import Optional

VARIAVEIS_SECRETAS = ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS")
NIVEIS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def mascarar(texto: str, segredos) -> str:
    """Troca cada segredo (com 4+ caracteres, para não mascarar letra solta) por •••."""
    for s in segredos:
        if s and len(s) >= 4:
            texto = texto.replace(s, "•••")
    return texto


class LogMemoria(logging.Handler):
    def __init__(self, capacidade: int = 500, nivel: int = logging.INFO):
        super().__init__(nivel)
        self._registros: deque = deque(maxlen=capacidade)
        self._trava = threading.Lock()
        self._seq = 0      # número crescente por registro: o horário repete (relógio do Windows) e chega fora de ordem

    def emit(self, record: logging.LogRecord):
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        if record.exc_info:
            msg += " | " + logging.Formatter().formatException(record.exc_info).splitlines()[-1]
        segredos = [os.environ.get(n, "") for n in VARIAVEIS_SECRETAS]
        registro = {"ts": record.created, "nivel": record.levelname,
                    "origem": record.name, "msg": mascarar(msg, segredos)}
        with self._trava:
            self._seq += 1
            registro["seq"] = self._seq
            self._registros.append(registro)

    @property
    def ultimo_seq(self) -> int:
        """Último seq emitido. Menor que o visto pela tela = servidor reiniciado (o seq recomeçou)."""
        with self._trava:
            return self._seq

    def registros(self, since: Optional[float] = None, nivel: str = "INFO",
                  apos: Optional[int] = None) -> list[dict]:
        """
        Registros com nível >= nivel, na ordem em que chegaram. Para buscar só os novos,
        use apos=<último seq visto> (não perde registros com o mesmo horário);
        since=<horário> continua aceito.
        """
        minimo = NIVEIS.get(str(nivel).upper())
        if minimo is None:
            raise ValueError(f"nível inválido: {nivel} (use {', '.join(NIVEIS)})")
        with self._trava:
            copia = list(self._registros)
        return [dict(r) for r in copia
                if (since is None or r["ts"] > since) and (apos is None or r["seq"] > apos)
                and NIVEIS.get(r["nivel"], 0) >= minimo]


_instalado: Optional[LogMemoria] = None


def instalar() -> LogMemoria:
    """Instala (uma vez só) o LogMemoria no logger raiz e o devolve."""
    global _instalado
    if _instalado is None:
        _instalado = LogMemoria()
        logging.getLogger().addHandler(_instalado)
    return _instalado
