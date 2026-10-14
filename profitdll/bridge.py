"""
PROFITDLL BRIDGE — Integração com a ProfitDLL da Nelogica (Market Data)
=======================================================================
Recebe cada negócio em tempo real pelo callback de trade V2 da DLL e
alimenta o FlowEngine. Diferente de RTD/DDE, não há polling: nenhum
negócio é perdido e o lado agressor vem pronto no TradeType.

Baseado no exemplo oficial da Nelogica ("Do tick ao dashboard: construa
sua análise de players com a ProfitDLL").

Requisitos (Windows):
  - ProfitDLL.dll de 64 bits e o profitTypes.py (pasta "Exemplo Python"
    do pacote da ProfitDLL)
  - Python 64 bits
  - Variáveis de ambiente:
      set PROFITDLL_KEY=sua_chave_de_ativacao
      set PROFITDLL_USER=seu_usuario_nelogica
      set PROFITDLL_PASS=sua_senha_de_login
      set PROFITDLL_PATH=C:\\ProfitDLL\\Win64\\ProfitDLL.dll
      set PROFITDLL_TYPES_DIR=C:\\ProfitDLL\\Exemplo Python   (onde está o profitTypes.py)
"""

import os
import sys
import json
import time
import logging
import threading
from queue import Queue, Empty
from typing import Optional, Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.engine import Tick, Side

logger = logging.getLogger("ProfitDLL")

# TradeType da ProfitDLL
AGRESSAO_COMPRA = 2
AGRESSAO_VENDA  = 3

# Estados de conexão (nConnStateType, nResult) do TStateCallback
_LOGIN, _MARKET, _ATIVACAO = 0, 2, 3
_LOGIN_CONNECTED   = 0
_MARKET_CONNECTED  = 4
_ATIVACAO_VALIDA   = 0

# Prefixos de derivativos BMF (bolsa "F"); demais ativos vão para Bovespa ("B")
_PREFIXOS_BMF = ("WIN", "WDO", "IND", "DOL", "BGI", "CCM", "ICF", "DI1", "WSP", "BIT")


def bolsa_padrao(ticker: str) -> str:
    """Código de bolsa da DLL para o ticker: F = BMF (futuros), B = Bovespa."""
    t = ticker.upper()
    if t.endswith("FUT") or t.startswith(_PREFIXOS_BMF):
        return "F"
    return "B"


def carregar_nomes_agentes(path: Optional[str]) -> dict[int, str]:
    """
    Lê um JSON {"codigo": "NOME"} para traduzir o código numérico da
    corretora (BuyAgent/SellAgent) no nome usado pelo engine, ex.:
      {"3": "XP INC", "8": "UBS"}
    Os nomes devem bater com EngineConfig.high_relevance_brokers para
    que o peso 2x funcione. Sem arquivo, o broker vira o código ("3").
    """
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {int(k): str(v).upper() for k, v in raw.items()}


def trade_para_tick(buy_agent: int, sell_agent: int, qty: int, price: float,
                    trade_type: int, timestamp: float,
                    nomes: Optional[dict[int, str]] = None) -> Optional[Tick]:
    """
    Converte um negócio da DLL em Tick do engine.
    O broker do Tick é o AGRESSOR (quem iniciou o negócio) e o
    passive_broker é a outra ponta (quem estava apregoado).
    Negócios sem agressão (cross, leilão etc.) retornam None: não
    representam pressão de nenhum lado.
    """
    if trade_type == AGRESSAO_COMPRA:
        side, agente, passivo = Side.BUY, buy_agent, sell_agent
    elif trade_type == AGRESSAO_VENDA:
        side, agente, passivo = Side.SELL, sell_agent, buy_agent
    else:
        return None
    if qty <= 0 or price <= 0:
        return None
    nomes = nomes or {}
    return Tick(
        timestamp = timestamp,
        price     = float(price),
        qty       = int(qty),
        broker    = nomes.get(agente, str(agente)),
        side      = side,
        passive_broker = nomes.get(passivo, str(passivo)),
    )


class ProfitDLLBridge:
    """
    Conecta na ProfitDLL, assina o ativo e entrega cada negócio ao
    callback on_tick (normalmente engine.add_tick).

    O callback da DLL só extrai e enfileira; uma thread consumidora
    converte e entrega ao engine, para nunca bloquear a thread da DLL.
    """

    def __init__(self, asset: str, exchange: Optional[str] = None,
                 agentes_path: Optional[str] = None, timeout: int = 30):
        self.asset    = asset
        self.exchange = exchange or bolsa_padrao(asset)
        self.timeout  = timeout
        self.nomes    = carregar_nomes_agentes(agentes_path)
        self.on_tick: Optional[Callable[[Tick], None]] = None

        self.fila: Queue = Queue()
        self.dll = None
        self._callbacks: list = []   # mantém os WINFUNCTYPE vivos (anti-GC)
        self._parar = threading.Event()
        self._consumidor: Optional[threading.Thread] = None
        self._estado = {k: threading.Event() for k in ("login", "market", "ativacao")}
        self.trades_recebidos = 0
        self.trades_ignorados = 0

    # ──────────────────────────────────────────────────────────
    # CICLO DE VIDA
    # ──────────────────────────────────────────────────────────

    def start(self) -> bool:
        try:
            self._conectar()
        except Exception as e:
            logger.error(f"Falha ao conectar na ProfitDLL: {e}")
            self.stop()
            return False

        self._parar.clear()
        self._consumidor = threading.Thread(target=self._consumir, daemon=True)
        self._consumidor.start()

        ret = self.dll.SubscribeTicker(self.asset, self.exchange)
        if ret != 0:
            logger.error(f"SubscribeTicker({self.asset}, {self.exchange}) falhou: código {ret}")
            self.stop()
            return False
        logger.info(f"ProfitDLL: assinatura ativa em {self.asset} (bolsa {self.exchange})")
        return True

    def stop(self):
        self._parar.set()
        if self._consumidor:
            self._consumidor.join(timeout=2)
        if self.dll is not None:
            # Cancelar a assinatura ANTES de finalizar a DLL
            try:
                if self._consumidor:
                    self.dll.UnsubscribeTicker(self.asset, self.exchange)
                self.dll.DLLFinalize()
            except Exception as e:
                logger.warning(f"Erro ao finalizar ProfitDLL: {e}")
            self.dll = None
        logger.info(f"ProfitDLL encerrada | trades: {self.trades_recebidos} "
                    f"| ignorados (sem agressão): {self.trades_ignorados}")

    # ──────────────────────────────────────────────────────────
    # CONEXÃO (específico da DLL / Windows)
    # ──────────────────────────────────────────────────────────

    def _conectar(self):
        if sys.platform != "win32":
            raise RuntimeError("a ProfitDLL só funciona no Windows")

        key  = os.getenv("PROFITDLL_KEY")
        user = os.getenv("PROFITDLL_USER")
        pwd  = os.getenv("PROFITDLL_PASS")
        faltando = [n for n, v in (("PROFITDLL_KEY", key), ("PROFITDLL_USER", user),
                                   ("PROFITDLL_PASS", pwd)) if not v]
        if faltando:
            raise RuntimeError("variáveis de ambiente não definidas: " + ", ".join(faltando))

        dll_path  = os.getenv("PROFITDLL_PATH", r"C:\ProfitDLL\Win64\ProfitDLL.dll")
        types_dir = os.getenv("PROFITDLL_TYPES_DIR")
        if types_dir and types_dir not in sys.path:
            sys.path.insert(0, types_dir)

        from ctypes import (WINFUNCTYPE, POINTER, WinDLL, byref,
                            c_int, c_uint, c_size_t, c_wchar_p)
        try:
            from profitTypes import TConnectorAssetIdentifier, TConnectorTrade
        except ImportError:
            raise RuntimeError("profitTypes.py não encontrado — defina PROFITDLL_TYPES_DIR "
                               "com a pasta 'Exemplo Python' do pacote da ProfitDLL")

        TStateCallback = WINFUNCTYPE(None, c_int, c_int)
        # Ativo chega POR VALOR; o trade é um ponteiro opaco lido com TranslateTrade
        TTradeCallback = WINFUNCTYPE(None, TConnectorAssetIdentifier, c_size_t, c_uint)

        # stdcall → WinDLL (CDLL corromperia a pilha silenciosamente)
        dll = WinDLL(dll_path)
        dll.DLLInitializeMarketLogin.restype = c_int
        dll.DLLFinalize.restype = c_int
        dll.SubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]
        dll.SubscribeTicker.restype = c_int
        dll.UnsubscribeTicker.argtypes = [c_wchar_p, c_wchar_p]
        dll.UnsubscribeTicker.restype = c_int
        dll.SetTradeCallbackV2.argtypes = [TTradeCallback]
        dll.SetTradeCallbackV2.restype = c_int
        dll.TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]
        dll.TranslateTrade.restype = c_int

        def on_estado(tipo, resultado):
            if tipo == _LOGIN and resultado == _LOGIN_CONNECTED:
                self._estado["login"].set()
            elif tipo == _MARKET and resultado == _MARKET_CONNECTED:
                self._estado["market"].set()
            elif tipo == _ATIVACAO and resultado == _ATIVACAO_VALIDA:
                self._estado["ativacao"].set()

        def on_trade(asset, p_trade, flags):
            # Só extrai e enfileira — roda na thread interna da DLL
            trade = TConnectorTrade()
            trade.Version = 0
            if dll.TranslateTrade(p_trade, byref(trade)) != 0:
                return
            self.fila.put((int(trade.BuyAgent), int(trade.SellAgent),
                           int(trade.Quantity), float(trade.Price),
                           int(trade.TradeType), time.time()))

        cb_estado = TStateCallback(on_estado)
        cb_trade  = TTradeCallback(on_trade)
        self._callbacks += [cb_estado, cb_trade]

        ret = dll.DLLInitializeMarketLogin(
            key, user, pwd,
            cb_estado,   # stateCallback
            None,        # newTradeCallback (V1) — usamos o V2
            None,        # newDailyCallback
            None,        # priceBookCallback
            None,        # offerBookCallback
            None,        # newHistoryCallback
            None,        # progressCallback
            None,        # newTinyBookCallback
        )
        if ret != 0:
            raise RuntimeError(f"DLLInitializeMarketLogin falhou: código {ret}")
        self.dll = dll

        dll.SetTradeCallbackV2(cb_trade)
        for nome in ("login", "market", "ativacao"):
            if not self._estado[nome].wait(self.timeout):
                raise TimeoutError(f"conexão não completou em {self.timeout}s (faltou: {nome})")
        logger.info("ProfitDLL conectada (login, market data e ativação OK)")

    # ──────────────────────────────────────────────────────────
    # CONSUMIDOR
    # ──────────────────────────────────────────────────────────

    def _consumir(self):
        while not self._parar.is_set():
            try:
                buy, sell, qty, price, ttype, ts = self.fila.get(timeout=0.5)
            except Empty:
                continue
            self._processar(buy, sell, qty, price, ttype, ts)

    def _processar(self, buy, sell, qty, price, ttype, ts):
        self.trades_recebidos += 1
        tick = trade_para_tick(buy, sell, qty, price, ttype, ts, self.nomes)
        if tick is None:
            self.trades_ignorados += 1
            return
        if self.on_tick:
            try:
                self.on_tick(tick)
            except Exception as e:
                logger.error(f"Erro ao processar tick: {e}")
