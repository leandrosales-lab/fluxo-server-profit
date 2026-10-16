"""
PROFITDLL BRIDGE — Integração com a ProfitDLL da Nelogica (Market Data)
=======================================================================
Recebe cada negócio em tempo real pelo callback de trade V2 da DLL e
alimenta o FlowEngine. Diferente de RTD/DDE, não há polling: nenhum
negócio é perdido e o lado agressor vem pronto no TradeType.

  - Horário do negócio: vem do TradeDate do TConnectorTrade (precisão de
    milissegundo, horário de Brasília) e é convertido para epoch com fuso
    fixo UTC-3 (sem tzdata). Se o campo vier vazio/zerado ou em formato
    desconhecido, usa o relógio local (time.time()) e conta o fallback.
    As conversões ficam em funções puras reutilizáveis:
      data_b3_para_epoch("14/10/2026 10:00:00.125")  → epoch (float)
      systemtime_para_epoch(st)  (struct com wYear..wMilliseconds) → epoch
      horario_negocio(trade_date) → epoch ou None (aceita os dois)
  - Topo do livro (TinyBook): o TTinyBookCallback entrega melhor compra
    (side 0) e melhor venda (side 1). A ponte guarda o último bid/ask e
    entrega ao callback on_book (normalmente engine.update_book) dois
    BookLevel sem corretora (o TinyBook não informa o agente).
  - Negócios e book passam pela MESMA fila, preservando a ordem de chegada.
  - Contadores em stats() (expostos no GET /state, bloco "dll").

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
import ntpath
import sys
import json
import time
import logging
import threading
from datetime import datetime, timedelta, timezone
from queue import Queue, Empty
from typing import Optional, Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.engine import Tick, Side, BookLevel

logger = logging.getLogger("ProfitDLL")

# TradeType da ProfitDLL
AGRESSAO_COMPRA = 2
AGRESSAO_VENDA  = 3
NOMES_TRADE_TYPE = {1: "cross", 2: "agressão de compra", 3: "agressão de venda", 4: "leilão",
                    5: "surveillance", 6: "expit", 7: "exercício de opções", 8: "balcão",
                    9: "termo", 10: "índice", 11: "BTC", 12: "on behalf", 13: "RLP",
                    14: "BBT", 15: "RFQ", 16: "MPT", 17: "TAC", 18: "TAA",
                    32: "desconhecido", 33: "update", 34: "mid", 35: "off exchange"}
CM_IS_SHORT_NAME = 1   # GetAgentName: nome abreviado da corretora

# Flag do TTradeCallback V2: o negócio é uma EDIÇÃO de um negócio já enviado
# (manual p.35). Não deve entrar no engine como negócio novo.
TC_IS_EDIT = 1

# Estados de conexão (nConnStateType, nResult) do TStateCallback (manual p.15-16, p.58)
_LOGIN, _MARKET, _ATIVACAO = 0, 2, 3
_LOGIN_CONNECTED   = 0
_MARKET_CONNECTED  = 4
_ATIVACAO_VALIDA   = 0
_ATIVACAO_INVALIDA = 1
_MARKET_PERFORMANCE_WARNING = 5
_MARKET_PARTIAL_CONNECTED   = 6   # callbacks atrasados/perdidos: o programa não está consumindo

_FALHAS_LOGIN = {1: "login inválido", 2: "senha inválida", 3: "senha bloqueada",
                 4: "senha expirada", 200: "erro interno de login"}
NOMES_MARKET = {0: "desconectado", 1: "conectando", 2: "aguardando conexão",
                3: "não logado", 4: "conectado", 5: "conectado (aviso de desempenho)",
                6: "parcialmente conectado"}
NOMES_LOGIN    = {0: "conectado", **_FALHAS_LOGIN}
NOMES_ATIVACAO = {0: "válida", 1: "inválida"}

CAMINHO_PADRAO_DLL = r"C:\ProfitDLL\Win64\ProfitDLL.dll"


def mascarar_caminho(caminho: Optional[str]) -> Optional[str]:
    """C:\\ProfitDLL\\Win64\\ProfitDLL.dll → C:\\…\\ProfitDLL.dll (a tela não mostra a pasta inteira)."""
    if not caminho:
        return None
    drive, _ = ntpath.splitdrive(caminho)
    nome = ntpath.basename(caminho)
    return f"{drive}\\…\\{nome}" if drive else f"…\\{nome}"


def _estado_nomeado(codigo: Optional[int], nomes: dict) -> Optional[dict]:
    """(código, nome) de um estado do TStateCallback, ou None se ainda não chegou."""
    if codigo is None:
        return None
    return {"codigo": codigo, "nome": nomes.get(codigo, f"código {codigo}")}

# Lado do TinyBook (TTinyBookCallback)
TINYBOOK_BID = 0
TINYBOOK_ASK = 1

# Horário da B3 = horário de Brasília. Fuso fixo UTC-3 (o Brasil não tem
# horário de verão desde 2019) — não depende de tzdata no Windows.
FUSO_B3 = timezone(timedelta(hours=-3))

# Prefixos de derivativos BMF (bolsa "F"); demais ativos vão para Bovespa ("B")
_PREFIXOS_BMF = ("WIN", "WDO", "IND", "DOL", "BGI", "CCM", "ICF", "DI1", "WSP", "BIT")


def bolsa_padrao(ticker: str) -> str:
    """Código de bolsa da DLL para o ticker: F = BMF (futuros), B = Bovespa."""
    t = ticker.upper()
    if t.endswith("FUT") or t.startswith(_PREFIXOS_BMF):
        return "F"
    return "B"


# ──────────────────────────────────────────────────────────────
# HORÁRIO DO NEGÓCIO (funções puras, reutilizadas pelo histórico)
# ──────────────────────────────────────────────────────────────

_FORMATOS_DATA_B3 = ("%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S")


def data_b3_para_epoch(texto) -> Optional[float]:
    """
    Converte a data da DLL "DD/MM/YYYY HH:mm:SS.ZZZ" (horário de Brasília)
    em epoch (segundos desde 1970, com milissegundos). Aceita também sem
    milissegundos e com vírgula no lugar do ponto. Formato inválido → None.
    """
    if isinstance(texto, bytes):
        texto = texto.decode("latin-1", errors="ignore")
    if not isinstance(texto, str):
        return None
    s = texto.strip().replace(",", ".")
    if not s:
        return None
    for fmt in _FORMATOS_DATA_B3:
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        return dt.replace(tzinfo=FUSO_B3).timestamp()
    return None


def systemtime_para_epoch(st) -> Optional[float]:
    """
    Converte um SYSTEMTIME (wYear, wMonth, wDay, wHour, wMinute, wSecond,
    wMilliseconds) em horário de Brasília para epoch. Qualquer objeto com
    esses atributos serve (struct ctypes ou objeto simples). Zerado
    (wYear == 0) ou inválido → None.
    """
    try:
        ano = int(st.wYear)
        if ano <= 0:
            return None
        dt = datetime(ano, int(st.wMonth), int(st.wDay),
                      int(getattr(st, "wHour", 0)), int(getattr(st, "wMinute", 0)),
                      int(getattr(st, "wSecond", 0)),
                      int(getattr(st, "wMilliseconds", 0)) * 1000,
                      tzinfo=FUSO_B3)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    return dt.timestamp()


def horario_negocio(trade_date) -> Optional[float]:
    """
    Epoch do TradeDate do TConnectorTrade, seja qual for a forma em que o
    profitTypes.py o declare: SYSTEMTIME (campos wYear...) ou texto
    "DD/MM/YYYY HH:mm:SS.ZZZ". Vazio, zerado ou desconhecido → None (o
    chamador usa o relógio local e conta o fallback).
    """
    if trade_date is None:
        return None
    if hasattr(trade_date, "wYear"):
        return systemtime_para_epoch(trade_date)
    if isinstance(trade_date, (str, bytes)):
        return data_b3_para_epoch(trade_date)
    return None


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


def topo_para_niveis(bid: Optional[tuple], ask: Optional[tuple],
                     timestamp: float) -> list[BookLevel]:
    """
    Monta o book do engine a partir do topo do livro (TinyBook):
    bid/ask = (preço, quantidade) ou None se o lado não tem oferta.
    O TinyBook não informa a corretora, então broker = "".
    """
    niveis = []
    if bid:
        niveis.append(BookLevel(price=bid[0], qty=bid[1], broker="",
                                side=Side.BUY, timestamp=timestamp))
    if ask:
        niveis.append(BookLevel(price=ask[0], qty=ask[1], broker="",
                                side=Side.SELL, timestamp=timestamp))
    return niveis


class ProfitDLLBridge:
    """
    Conecta na ProfitDLL, assina o ativo e entrega cada negócio ao
    callback on_tick (normalmente engine.add_tick) e cada mudança do topo
    do livro ao callback on_book (normalmente engine.update_book).

    Os callbacks da DLL só extraem e enfileiram tipos Python; uma thread
    consumidora converte e entrega ao engine, para nunca bloquear a thread
    da DLL. Eventos na fila (uma só, para manter a ordem de chegada):
      ("trade", buy_agent, sell_agent, qty, price, trade_type, epoch_ou_None, flags, trade_number)
        (flags e trade_number são opcionais; flags com TC_IS_EDIT = edição, descartada)
      ("book",  lado (0 bid / 1 ask), price, qty, time.time() da chegada)
    """

    def __init__(self, asset: str, exchange: Optional[str] = None,
                 agentes_path: Optional[str] = None, timeout: int = 30):
        self.asset    = asset
        self.exchange = exchange or bolsa_padrao(asset)
        self.timeout  = timeout
        self.nomes    = carregar_nomes_agentes(agentes_path)
        self.on_tick: Optional[Callable[[Tick], None]] = None
        self.on_book: Optional[Callable[[list[BookLevel]], None]] = None

        self.fila: Queue = Queue()
        self.dll = None
        self._callbacks: list = []   # mantém os WINFUNCTYPE vivos (anti-GC)
        self._parar = threading.Event()
        self._consumidor: Optional[threading.Thread] = None
        self._estado = {k: threading.Event() for k in ("login", "market", "ativacao")}
        self._falha = threading.Event()          # login/ativação recusados: aborta a espera
        self.motivo_falha: Optional[str] = None
        self._conectado = False                  # True depois que os três estados ficaram OK
        self.resultado_market: Optional[int] = None
        self.resultado_login: Optional[int] = None
        self.resultado_ativacao: Optional[int] = None
        self.latencia_ms: Optional[int] = None   # chegada ao consumidor − horário do negócio
        # Contadores (stats())
        self.trades_recebidos  = 0
        self.trades_editados   = 0    # flag TC_IS_EDIT: edição de negócio já enviado (descartada)
        self.quedas_market     = 0    # market data saiu de "conectado" depois do start
        self.avisos_partial    = 0    # estado (2,6): callbacks atrasados ou perdidos
        self.trades_ignorados  = 0    # sem agressão (cross, leilão) ou inválidos
        self.horarios_fallback = 0    # TradeDate ausente/inválido → relógio local
        self.book_atualizacoes = 0
        self.ignorados_por_tipo: dict[int, int] = {}   # TradeType → quantidade descartada
        self._nomes_dll: dict[int, str] = {}           # cache código → nome abreviado da DLL
        # Topo do livro atual: (preço, quantidade) ou None
        self.bid: Optional[tuple] = None
        self.ask: Optional[tuple] = None
        self._ultimo_ts_negocio: Optional[float] = None

    def stats(self) -> dict:
        """Contadores da ponte (bloco "dll" do GET /state)."""
        return {
            "conectado":         self._conectado,
            "estado_market":     NOMES_MARKET.get(self.resultado_market, self.resultado_market),
            "quedas_market":     self.quedas_market,
            "avisos_partial":    self.avisos_partial,
            "trades_recebidos":  self.trades_recebidos,
            "trades_editados":   self.trades_editados,
            "trades_ignorados":  self.trades_ignorados,
            "ignorados_por_tipo": {NOMES_TRADE_TYPE.get(t, str(t)): n
                                   for t, n in sorted(self.ignorados_por_tipo.items())},
            "horarios_fallback": self.horarios_fallback,
            "book_atualizacoes": self.book_atualizacoes,
            "fila_pendente":     self.fila.qsize(),
            "bid":               list(self.bid) if self.bid else None,
            "ask":               list(self.ask) if self.ask else None,
            "motivo_falha":      self.motivo_falha,
            "estados": {
                "login":    _estado_nomeado(self.resultado_login, NOMES_LOGIN),
                "ativacao": _estado_nomeado(self.resultado_ativacao, NOMES_ATIVACAO),
                "market":   _estado_nomeado(self.resultado_market, NOMES_MARKET),
            },
            "latencia_ms":       self.latencia_ms,
            "ativo":             self.asset,
            "bolsa":             self.exchange,
            "dll_path":          mascarar_caminho(os.getenv("PROFITDLL_PATH", CAMINHO_PADRAO_DLL)),
        }

    # ──────────────────────────────────────────────────────────
    # CICLO DE VIDA
    # ──────────────────────────────────────────────────────────

    def start(self) -> bool:
        self._resetar_conexao()
        try:
            self._conectar()
        except Exception as e:
            self.motivo_falha = self.motivo_falha or str(e)
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
        self._conectado = False
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
        self._consumidor = None
        logger.info(f"ProfitDLL encerrada | trades: {self.trades_recebidos} "
                    f"| ignorados (sem agressão): {self.trades_ignorados} "
                    f"| horário local (fallback): {self.horarios_fallback} "
                    f"| book: {self.book_atualizacoes}")

    def _resetar_conexao(self):
        """
        Zera o estado de CONEXÃO antes de cada start(): eventos de login/ativação/market,
        falha anterior, topo do livro e a fila antiga. Os contadores continuam acumulando
        (a tela Conexão mostra o dia inteiro, com as reconexões).
        """
        for evento in self._estado.values():
            evento.clear()
        self._falha.clear()
        self.motivo_falha = None
        self._conectado = False
        self.resultado_market = self.resultado_login = self.resultado_ativacao = None
        self.bid = self.ask = None
        while True:
            try:
                self.fila.get_nowait()
            except Empty:
                break

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

        dll_path  = os.getenv("PROFITDLL_PATH", CAMINHO_PADRAO_DLL)
        types_dir = os.getenv("PROFITDLL_TYPES_DIR")
        if types_dir and types_dir not in sys.path:
            sys.path.insert(0, types_dir)

        from ctypes import (WINFUNCTYPE, POINTER, WinDLL, Structure, byref,
                            c_int, c_uint, c_size_t, c_double, c_wchar_p)
        try:
            from profitTypes import TConnectorAssetIdentifier, TConnectorTrade
        except ImportError:
            raise RuntimeError("profitTypes.py não encontrado — defina PROFITDLL_TYPES_DIR "
                               "com a pasta 'Exemplo Python' do pacote da ProfitDLL")
        try:
            from profitTypes import TAssetID
        except ImportError:
            # Definição da documentação (Funções Real Time / trades históricos)
            class TAssetID(Structure):
                _fields_ = [("ticker", c_wchar_p), ("bolsa", c_wchar_p), ("feed", c_int)]

        TStateCallback = WINFUNCTYPE(None, c_int, c_int)
        # Ativo chega POR VALOR; o trade é um ponteiro opaco lido com TranslateTrade
        TTradeCallback = WINFUNCTYPE(None, TConnectorAssetIdentifier, c_size_t, c_uint)
        # Topo do livro: (ativo por valor, preço, quantidade, lado 0 = bid / 1 = ask)
        TTinyBookCallback = WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int)

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
        dll.GetAgentNameLength.argtypes = [c_int, c_uint]
        dll.GetAgentNameLength.restype = c_int
        dll.GetAgentName.argtypes = [c_int, c_int, c_wchar_p, c_uint]
        dll.GetAgentName.restype = c_int

        def on_estado(tipo, resultado):
            self._on_estado(tipo, resultado)

        def on_trade(asset, p_trade, flags):
            # Só extrai e enfileira — roda na thread interna da DLL
            trade = TConnectorTrade()
            trade.Version = 0
            if dll.TranslateTrade(p_trade, byref(trade)) != 0:
                return
            # Horário convertido aqui mesmo (barato): a struct não sobrevive ao callback
            self.fila.put(("trade", int(trade.BuyAgent), int(trade.SellAgent),
                           int(trade.Quantity), float(trade.Price),
                           int(trade.TradeType), horario_negocio(trade.TradeDate),
                           int(flags), int(trade.TradeNumber)))

        def on_tiny_book(asset, price, qty, side):
            # Só enfileira — o TinyBook não traz horário, marca a chegada
            self.fila.put(("book", int(side), float(price), int(qty), time.time()))

        cb_estado = TStateCallback(on_estado)
        cb_trade  = TTradeCallback(on_trade)
        cb_tiny   = TTinyBookCallback(on_tiny_book)
        self._callbacks += [cb_estado, cb_trade, cb_tiny]

        ret = dll.DLLInitializeMarketLogin(
            key, user, pwd,
            cb_estado,   # stateCallback
            None,        # newTradeCallback (V1) — usamos o V2
            None,        # newDailyCallback
            None,        # priceBookCallback
            None,        # offerBookCallback
            None,        # newHistoryCallback
            None,        # progressCallback
            cb_tiny,     # newTinyBookCallback (melhor compra/venda)
        )
        if ret != 0:
            raise RuntimeError(f"DLLInitializeMarketLogin falhou: código {ret}")
        self.dll = dll

        dll.SetTradeCallbackV2(cb_trade)
        self._aguardar_conexao()

    # ──────────────────────────────────────────────────────────
    # ESTADO DA CONEXÃO (sem DLL, testável)
    # ──────────────────────────────────────────────────────────

    def _on_estado(self, tipo: int, resultado: int):
        """
        Trata o TStateCallback. Roda na thread da DLL: só atualiza flags,
        contadores e log. Login/ativação recusados disparam _falha, que
        aborta a espera de _aguardar_conexao na hora.
        """
        if tipo == _LOGIN:
            self.resultado_login = resultado
            if resultado == _LOGIN_CONNECTED:
                self._estado["login"].set()
            else:
                self._estado["login"].clear()
                self._registrar_falha(_FALHAS_LOGIN.get(resultado, f"login recusado (código {resultado})"))
        elif tipo == _ATIVACAO:
            self.resultado_ativacao = resultado
            if resultado == _ATIVACAO_VALIDA:
                self._estado["ativacao"].set()
            elif resultado == _ATIVACAO_INVALIDA:
                self._estado["ativacao"].clear()
                self._registrar_falha("ativação inválida (confira PROFITDLL_KEY)")
        elif tipo == _MARKET:
            self.resultado_market = resultado
            if resultado == _MARKET_CONNECTED:
                if not self._estado["market"].is_set() and self.quedas_market:
                    logger.info("ProfitDLL: market data reconectado")
                self._estado["market"].set()
            elif resultado == _MARKET_PERFORMANCE_WARNING:
                logger.warning("ProfitDLL: aviso de desempenho do market data (2,5)")
            elif resultado == _MARKET_PARTIAL_CONNECTED:
                self.avisos_partial += 1
                logger.critical("ProfitDLL: estado (2,6) — callbacks atrasados ou perdidos; "
                                "o programa não está consumindo os dados a tempo")
            else:
                if self._conectado and self._estado["market"].is_set():
                    self.quedas_market += 1
                    logger.error(f"ProfitDLL: market data caiu — "
                                 f"{NOMES_MARKET.get(resultado, resultado)} (2,{resultado})")
                self._estado["market"].clear()
        self._conectado_agora()

    def _conectado_agora(self) -> bool:
        tudo_ok = all(e.is_set() for e in self._estado.values())
        if tudo_ok:
            self._conectado = True
        elif self._conectado and not self._estado["market"].is_set():
            self._conectado = False
        return tudo_ok

    def _registrar_falha(self, motivo: str):
        self.motivo_falha = motivo
        self._conectado = False
        self._falha.set()
        logger.error(f"ProfitDLL: {motivo}")

    def _aguardar_conexao(self):
        """
        Espera login, market data e ativação. Falha de login/ativação aborta
        na hora (RuntimeError com o motivo); sem resposta, TimeoutError
        dizendo o que faltou.
        """
        limite = time.time() + self.timeout
        while True:
            if self._falha.is_set():
                raise RuntimeError(f"conexão recusada: {self.motivo_falha}")
            if self._conectado_agora():
                logger.info("ProfitDLL conectada (login, market data e ativação OK)")
                return
            if time.time() >= limite:
                faltou = [n for n, e in self._estado.items() if not e.is_set()]
                raise TimeoutError(f"conexão não completou em {self.timeout}s "
                                   f"(faltou: {', '.join(faltou)})")
            self._falha.wait(0.05)

    # ──────────────────────────────────────────────────────────
    # CONSUMIDOR
    # ──────────────────────────────────────────────────────────

    def _consumir(self):
        while not self._parar.is_set():
            try:
                evento = self.fila.get(timeout=0.5)
            except Empty:
                continue
            self._processar_evento(evento)

    def _processar_evento(self, evento: tuple):
        """Despacha um evento da fila (trade ou book) — sem DLL, testável."""
        try:
            if evento[0] == "trade":
                self._processar_trade(*evento[1:])
            elif evento[0] == "book":
                self._processar_book(*evento[1:])
            else:
                logger.warning(f"Evento desconhecido na fila da DLL: {evento[0]!r}")
        except Exception as e:
            logger.error(f"Erro ao processar evento da DLL: {e}")

    def _nomes_para(self, *codigos: int) -> dict[int, str]:
        """Nomes das corretoras do negócio: JSON (--agentes) vence; senão a DLL."""
        return {c: self.nomes.get(c) or self._nome_agente(c) for c in codigos}

    def _nome_agente(self, codigo: int) -> str:
        """
        Nome abreviado da corretora pela DLL (GetAgentName), em cache.
        Roda na thread consumidora, nunca dentro de callback da DLL.
        Sem DLL ou sem nome, devolve o próprio código (sem cache: tenta de novo).
        """
        if codigo in self._nomes_dll:
            return self._nomes_dll[codigo]
        nome = str(codigo)
        dll = self.dll
        if dll is not None and codigo > 0:
            try:
                from ctypes import create_unicode_buffer
                tam = dll.GetAgentNameLength(codigo, CM_IS_SHORT_NAME)
                if tam > 0:
                    buf = create_unicode_buffer(tam + 1)   # +1: terminador
                    if dll.GetAgentName(tam + 1, codigo, buf, CM_IS_SHORT_NAME) >= 0 and buf.value.strip():
                        nome = buf.value.strip().upper()
                        self._nomes_dll[codigo] = nome   # só guarda acerto: a lista pode chegar depois
            except Exception as e:
                logger.warning(f"GetAgentName({codigo}) falhou: {e}")
        return nome

    def _processar_trade(self, buy, sell, qty, price, ttype, ts, flags=0, numero=None):
        if flags & TC_IS_EDIT:
            # Edição de um negócio já enviado. O manual não diz como casar com o
            # original no V2; até confirmar no teste real, descarta e conta.
            self.trades_editados += 1
            logger.info(f"Edição de negócio #{numero}: {qty} @ {price} (tipo {ttype}) — ignorada")
            return
        self.trades_recebidos += 1
        if ts is None:
            self.horarios_fallback += 1
            ts = time.time()
        else:
            self.latencia_ms = max(0, round((time.time() - ts) * 1000))
        tick = trade_para_tick(buy, sell, qty, price, ttype, ts, self._nomes_para(buy, sell))
        if tick is None:
            self.trades_ignorados += 1
            self.ignorados_por_tipo[ttype] = self.ignorados_por_tipo.get(ttype, 0) + 1
            return
        self._ultimo_ts_negocio = tick.timestamp
        if self.on_tick:
            try:
                self.on_tick(tick)
            except Exception as e:
                logger.error(f"Erro ao processar tick: {e}")

    def _processar_book(self, lado, price, qty, ts_chegada):
        """
        Atualiza o topo do livro e entrega o snapshot (bid + ask) ao engine.
        Preço ou quantidade <= 0 = lado sem oferta (ex.: leilão).
        O timestamp é o do último negócio (relógio da B3), para não
        misturar com o relógio local; sem negócio ainda, usa a chegada.
        """
        topo = (float(price), int(qty)) if price > 0 and qty > 0 else None
        if lado == TINYBOOK_BID:
            self.bid = topo
        elif lado == TINYBOOK_ASK:
            self.ask = topo
        else:
            return
        self.book_atualizacoes += 1
        ts = self._ultimo_ts_negocio if self._ultimo_ts_negocio is not None else ts_chegada
        if self.on_book:
            try:
                self.on_book(topo_para_niveis(self.bid, self.ask, ts))
            except Exception as e:
                logger.error(f"Erro ao processar book: {e}")
