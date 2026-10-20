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
  - Livro de ofertas (book completo por ordem, com corretora): SetOfferBookCallbackV2 +
    SubscribeOfferBook do papel principal. O callback só copia os bytes dos arrays e enfileira
    ("oferta", ...); a thread consumidora aplica em profitdll.livro.LivroOfertas e entrega
    on_book(níveis com ordens/corretoras) no máximo ~5 vezes por segundo. O TinyBook continua
    como fallback: se a assinatura falhar, o livro estiver vazio ou divergir do TinyBook por
    mais de 1 s, o topo do TinyBook é entregue como antes.
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
import ctypes
from datetime import datetime, timedelta, timezone
from queue import Queue, Empty
from typing import Optional, Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.engine import Tick, Side, BookLevel
from profitdll.livro import (LivroOfertas, decodifica_array_v2, CABECALHO_V2, AT_FULLBOOK,
                             LADO_COMPRA, LADO_VENDA)
from core.livro_ofertas import LivroOfertas as LivroGiro
from profitdll.livro import LivroOfertas as LivroPos

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

# Livro de ofertas
INTERVALO_LIVRO_PADRAO = 0.2     # s entre snapshots entregues (~5 por segundo)
NIVEIS_LIVRO_PADRAO    = 15      # níveis por lado entregues ao engine
TOLERANCIA_DIVERGENCIA = 1.0     # s que o livro pode divergir do TinyBook antes de voltar ao topo
MAX_ARRAY_BYTES        = 64 * 1024 * 1024


def copiar_array_v2(ptr) -> Optional[bytes]:
    """
    Copia o array V2 (POINTER(c_ubyte)) da DLL para bytes. O ponteiro só vale DENTRO do callback,
    então a cópia é feita ali; o tamanho vem do cabeçalho (int32 Q, int32 tamanho). Ponteiro nulo
    -> None. Cabeçalho com tamanho absurdo -> só os 8 bytes do cabeçalho (o decodificador rejeita).
    """
    if not ptr:
        return None
    endereco = ctypes.cast(ptr, ctypes.c_void_p).value
    if not endereco:
        return None
    cabecalho = ctypes.string_at(endereco, CABECALHO_V2.size)
    _q, tamanho = CABECALHO_V2.unpack(cabecalho)
    if tamanho < CABECALHO_V2.size or tamanho > MAX_ARRAY_BYTES:
        return cabecalho
    return ctypes.string_at(endereco, tamanho)


# Ações do livro de ofertas (manual p.8, p.61)
OFERTA_ADD, OFERTA_EDIT, OFERTA_DELETE, OFERTA_DELETE_FROM, OFERTA_FULL = 0, 1, 2, 3, 4
OB_LAST_PACKET, OB_FIRST_PACKET = 1, 2

# Horário da B3 = horário de Brasília. Fuso fixo UTC-3 (o Brasil não tem
# horário de verão desde 2019) — não depende de tzdata no Windows.
FUSO_B3 = timezone(timedelta(hours=-3))

# O sistema trabalha só com ações: toda assinatura vai para a Bovespa ("B").
BOLSA = "B"
# Prefixos de derivativos da BMF — recusados com mensagem clara em vez de uma assinatura que não chega
_PREFIXOS_FUTUROS = ("WIN", "WDO", "IND", "DOL", "BGI", "CCM", "ICF", "DI1", "WSP", "BIT")


def ticker_do_ativo(asset) -> str:
    """Papel de um identificador da DLL. Atenção: TConnectorAssetIdentifier (negócios) usa "Ticker",
    com T maiúsculo (profitTypes.py); TAssetID (TinyBook) usa "ticker"."""
    return str(getattr(asset, "Ticker", None) or getattr(asset, "ticker", None) or "").upper()


def validar_ativo(ticker: str) -> str:
    """Ticker normalizado (maiúsculo); ValueError para contrato futuro."""
    t = ticker.strip().upper()
    if t.endswith("FUT") or t.startswith(_PREFIXOS_FUTUROS):
        raise ValueError(f"{t} é contrato futuro; o Fluxo Server trabalha só com ações (ex.: PETR4)")
    return t


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


def decodificar_ofertas(blob: bytes) -> tuple[list[tuple], bool, bool]:
    """Lê um array de full book V2 (manual p.65–66).

    Devolve (ofertas, primeiro, ultimo). Cada oferta é (offer_id, preço, qtd, agente).
    Sem flag de pacote, o bloco é um livro inteiro.
    """
    import struct
    if not blob or len(blob) < 8:
        return [], True, True
    qtd, tamanho = struct.unpack_from("ii", blob, 0)
    if qtd < 0 or qtd > 20000:
        return [], True, True
    frame_end = 8 + qtd * 53
    flags = struct.unpack_from("I", blob, frame_end)[0] if frame_end + 4 <= len(blob) else 0
    ofertas = []
    pos = 8
    for _ in range(qtd):
        if pos + 30 > len(blob):
            break
        price, qty, agent, offer_id, date_len = struct.unpack_from("=dqiqH", blob, pos)
        pos += 30 + max(0, int(date_len))
        if qty <= 0 or price <= 0 or agent <= 0 or offer_id == 0:
            continue
        ofertas.append((int(offer_id), float(price), int(qty), int(agent)))
    primeiro = bool(flags & OB_FIRST_PACKET)
    ultimo = bool(flags & OB_LAST_PACKET)
    if not primeiro and not ultimo:
        primeiro = ultimo = True
    return ofertas, primeiro, ultimo


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
      ("oferta", acao, posicao, lado, price, qty, agente, offer_id, bytes_array_venda|None,
                 bytes_array_compra|None, time.time() da chegada)      livro de ofertas (V2)
    """

    def __init__(self, asset: str, agentes_path: Optional[str] = None, timeout: int = 30,
                 extras: Optional[list] = None, intervalo_livro: float = INTERVALO_LIVRO_PADRAO,
                 niveis_livro: int = NIVEIS_LIVRO_PADRAO):
        self.asset    = validar_ativo(asset)
        self.exchange = BOLSA
        # Radar: além do papel principal, a lista de ações (papel inválido/futuro vai para recusados)
        self.papeis: list[str] = [self.asset]
        self.recusados: list[str] = []
        for p in extras or []:
            try:
                p = validar_ativo(p)
            except ValueError:
                self.recusados.append(p.strip().upper())
                continue
            if p not in self.papeis:
                self.papeis.append(p)
        self.assinados = 0
        self.timeout  = timeout
        self.nomes    = carregar_nomes_agentes(agentes_path)
        self.on_tick: Optional[Callable[[Tick], None]] = None
        self.on_book: Optional[Callable[[list[BookLevel]], None]] = None
        # Giro de iceberg: (ativo, corretora, lado, preco, ts) quando o lote volta ao book
        self.on_renovacao: Optional[Callable[..., None]] = None
        # Histórico do dia do papel aberto: (ativo, [Tick]) quando o download termina (ordem cronológica)
        self.on_historico: Optional[Callable[[str, list], None]] = None
        self._hist_buffer: dict[str, list] = {}
        self._hist_lock = threading.Lock()
        self._hist_disponivel = False
        self.historico: dict = {"ativo": None, "progresso": 0, "negocios": 0, "estado": "parado"}
        self._livro_giro = LivroGiro()
        # diagnóstico do giro: por ação do livro (0 add, 1 edit, 2 delete, 3 delete_from, 4 full), quantas chegaram
        # e quantas traziam offer_id / agente / preço; e quantos giros foram emitidos
        self.oferta_acoes: dict[int, list] = {}
        self.renovacoes_emitidas = 0
        # EDIT/DELETE/DELETE_FROM do livro de ofertas chegam só com lado e POSIÇÃO (sem offer_id, agente nem
        # preço): para o giro, cada papel mantém o livro por posição e traduz o evento na ordem afetada
        self._livros_pos: dict[str, LivroPos] = {}
        self._pacote_pos: dict[tuple, list] = {}
        self.giro_erros = 0
        self.giro_erros_motivo: dict[str, int] = {}
        self.amostra_erro: list = []      # diagnóstico: (motivo, papel, ação, lado, posição, tamanho da lista)
        self.amostra_edit: list = []      # diagnóstico: últimos EDIT (papel, lado, posição, nQtd, qtd da ordem antes)
        self._pacote: dict[tuple, list] = {}
        self.livros_assinados = 0
        self.livros_recusados: list[str] = []

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
        # Livro de ofertas (book completo por ordem)
        self.livro = LivroOfertas()
        self.intervalo_livro = intervalo_livro
        self.niveis_livro = niveis_livro
        self.livro_ativo = False             # SubscribeOfferBook aceito (False = só TinyBook)
        self.livro_atualizacoes = 0          # snapshots do livro entregues ao on_book
        self.livro_divergencias = 0          # vezes que o livro divergiu do TinyBook > 1 s (voltou ao topo)
        self._livro_disponivel = False       # SetOfferBookCallbackV2 registrado
        self._livro_pendente = False         # há atualização retida pela limitação de taxa
        self._ultimo_envio_livro = float("-inf")
        self._modo_book: Optional[str] = None   # o que foi entregue por último: "ofertas" | "topo"
        self._tiny_visto = False
        self._diverge_desde: Optional[float] = None
        self._em_divergencia = False
        self._nomes_falha: dict[int, float] = {}   # código sem nome na DLL: quando tentou (evita insistir)
        self._agora = time.monotonic         # relógio da limitação de taxa (trocável nos testes)

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
            "livro_ativo":       self.livro_ativo,
            "livro_ordens":      self.livro.ordens_total,
            "livro_erros":       self.livro.erros,
            "livro_atualizacoes": self.livro_atualizacoes,
            "livro_divergencias": self.livro_divergencias,
            "livro_fonte":       self._modo_book,
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
            "papeis":            {"pedidos": len(self.papeis), "assinados": self.assinados,
                                  "recusados": list(self.recusados)},
            "historico":         dict(self.historico),
            "giro_diagnostico":  {"acoes": {str(k): {"n": v[0], "com_offer_id": v[1], "com_agente": v[2], "com_preco": v[3]}
                                            for k, v in self.oferta_acoes.items()},
                                  "renovacoes": self.renovacoes_emitidas, "erros": self.giro_erros,
                                  "erros_motivo": dict(self.giro_erros_motivo),
                                  "amostra_erro": [list(a) for a in self.amostra_erro],
                                  "amostra_edit": [list(a) for a in self.amostra_edit],
                                  "papeis_com_livro": len(self._livros_pos)},
            "livros":            {"assinados": self.livros_assinados,
                                  "recusados": list(self.livros_recusados)},
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
        self.assinados = 1
        for p in self.papeis[1:]:
            if self.dll.SubscribeTicker(p, self.exchange) == 0:
                self.assinados += 1
            else:
                self.recusados.append(p)
        self._assinar_livros()
        logger.info(f"ProfitDLL: assinatura ativa em {self.asset}"
                    + (f" + {self.assinados - 1} papéis do radar ({len(self.recusados)} recusados)"
                       if len(self.papeis) > 1 else "")
                    + (f"; livro de ofertas em {self.livros_assinados}"
                       + (f" ({len(self.livros_recusados)} recusados)" if self.livros_recusados else "")
                       if self.livros_assinados or self.livros_recusados else "")
                    + f" (bolsa {self.exchange})")
        return True

    def _assinar_livros(self) -> None:
        """Livro por oferta: é daqui que sai o giro (lote consumido e reposto)."""
        assinar = getattr(self.dll, "SubscribeOfferBook", None)
        if assinar is None:
            return
        for p in self.papeis:
            try:
                ok = assinar(p, self.exchange) == 0
            except Exception as e:
                logger.warning(f"SubscribeOfferBook({p}) falhou: {e}")
                ok = False
            if ok:
                self.livros_assinados += 1
            else:
                self.livros_recusados.append(p)
        # o livro da tela é o do papel principal; sem ele o TinyBook segue valendo
        self.livro_ativo = (self._livro_disponivel and self.asset not in self.livros_recusados
                            and self.livros_assinados > 0)
        if self.livro_ativo:
            logger.info(f"ProfitDLL: livro de ofertas assinado em {self.asset}")
        else:
            logger.warning(f"livro de ofertas indisponível em {self.asset} - usando só o topo (TinyBook)")

    def stop(self):
        self._parar.set()
        self._conectado = False
        if self._consumidor:
            self._consumidor.join(timeout=2)
        if self.dll is not None:
            # Cancelar a assinatura ANTES de finalizar a DLL
            try:
                if self._consumidor:
                    cancelar_livro = getattr(self.dll, "UnsubscribeOfferBook", None)
                    for p in self.papeis:
                        self.dll.UnsubscribeTicker(p, self.exchange)
                        if cancelar_livro is not None:
                            try:
                                cancelar_livro(p, self.exchange)
                            except Exception:
                                pass
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
        self._parar.clear()      # volta a aceitar estados da DLL (ignorados só depois de stop())
        self._falha.clear()
        self.motivo_falha = None
        self._conectado = False
        self.resultado_market = self.resultado_login = self.resultado_ativacao = None
        self.bid = self.ask = None
        self.livro.limpar()            # os contadores (erros) acumulam; o livro recomeça vazio
        self.livro_ativo = False
        self._livro_disponivel = False
        self._livro_pendente = False
        self._modo_book = None
        self._tiny_visto = False
        self._diverge_desde = None
        self._em_divergencia = False
        self._livro_giro.reset()
        self._livros_pos.clear()
        self._pacote_pos.clear()
        self._pacote.clear()
        self.livros_assinados = 0
        self.livros_recusados = []
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
                            c_int, c_uint, c_size_t, c_double, c_wchar_p, c_longlong, c_ubyte)
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
        # Livro de ofertas V2: ação, posição, lado, qtd, agente, offer_id, preço, bHas* (preço, qtd, data,
        # offer_id, agente), data e os arrays FullBook (venda, compra). nQtd é Int64 (manual p.53); o
        # exemplo oficial declara c_int e desalinha o resto.
        TOfferBookCallbackV2 = WINFUNCTYPE(
            None, TAssetID, c_int, c_int, c_int, c_longlong, c_int, c_longlong, c_double,
            c_int, c_int, c_int, c_int, c_int, c_wchar_p, POINTER(c_ubyte), POINTER(c_ubyte))

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
        # Histórico do dia (artigo da Nelogica): negócio a negócio + progresso 0-100 por papel
        THistoryTradeCallback = WINFUNCTYPE(None, TAssetID, c_wchar_p, c_uint, c_double, c_double,
                                            c_int, c_int, c_int, c_int)
        TProgressCallback = WINFUNCTYPE(None, TAssetID, c_int)
        if hasattr(dll, "GetHistoryTrades"):
            dll.GetHistoryTrades.argtypes = [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p]
            dll.GetHistoryTrades.restype = c_int
            dll.SetHistoryTradeCallback.argtypes = [THistoryTradeCallback]
            dll.SetHistoryTradeCallback.restype = c_int
            dll.SetSerieProgressCallback.argtypes = [TProgressCallback]
            dll.SetSerieProgressCallback.restype = c_int
        dll.TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]
        dll.TranslateTrade.restype = c_int
        dll.SubscribeOfferBook.argtypes = [c_wchar_p, c_wchar_p]
        dll.SubscribeOfferBook.restype = c_int
        dll.UnsubscribeOfferBook.argtypes = [c_wchar_p, c_wchar_p]
        dll.UnsubscribeOfferBook.restype = c_int
        dll.SetOfferBookCallbackV2.argtypes = [TOfferBookCallbackV2]
        dll.SetOfferBookCallbackV2.restype = c_int
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
                           int(flags), int(trade.TradeNumber), ticker_do_ativo(asset)))

        def on_tiny_book(asset, price, qty, side):
            if ticker_do_ativo(asset) != self.asset:
                return              # radar: topo do livro só do papel principal
            # Só enfileira — o TinyBook não traz horário, marca a chegada
            self.fila.put(("book", int(side), float(price), int(qty), time.time()))

        def on_oferta(asset, acao, posicao, lado, qtd, agente, offer_id, preco, tem_preco, tem_qtd,
                      tem_data, tem_offer_id, tem_agente, data, p_venda, p_compra):
            # Roda na thread da DLL: só copia os bytes dos arrays (o ponteiro só vale aqui) e enfileira.
            # Um único callback serve o giro do radar (todos os papéis) e o livro da tela (papel principal).
            try:
                arr_venda = arr_compra = None
                if acao == AT_FULLBOOK:
                    arr_venda, arr_compra = copiar_array_v2(p_venda), copiar_array_v2(p_compra)
                self.fila.put(("offer", ticker_do_ativo(asset), int(acao), int(posicao), int(lado),
                               int(qtd), int(agente), int(offer_id), float(preco),
                               int(tem_preco), int(tem_qtd), int(tem_offer_id), int(tem_agente),
                               arr_compra, arr_venda, time.time()))
            except Exception:
                self.livro.erros += 1

        cb_estado = TStateCallback(on_estado)
        cb_trade  = TTradeCallback(on_trade)
        cb_tiny   = TTinyBookCallback(on_tiny_book)
        cb_oferta = TOfferBookCallbackV2(on_oferta)

        def on_historico(asset, data, numero, preco, vol, qtd, comprador, vendedor, tipo):
            # Thread da DLL: só acumula; a conversão acontece na thread consumidora
            with self._hist_lock:
                self._hist_buffer.setdefault(ticker_do_ativo(asset), []).append(
                    (data, numero, preco, vol, qtd, comprador, vendedor, tipo))

        def on_progresso(asset, progresso):
            ativo_p = ticker_do_ativo(asset)
            if ativo_p == self.historico.get("ativo"):
                self.historico["progresso"] = int(progresso)
            if progresso >= 100:
                self.fila.put(("hist_fim", ativo_p))

        cb_hist = THistoryTradeCallback(on_historico)
        cb_prog = TProgressCallback(on_progresso)
        self._callbacks += [cb_estado, cb_trade, cb_tiny, cb_oferta, cb_hist, cb_prog]

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
        try:
            self._livro_disponivel = dll.SetOfferBookCallbackV2(cb_oferta) == 0
        except Exception as e:      # DLL sem a função: segue só com o TinyBook
            logger.warning(f"SetOfferBookCallbackV2 indisponível: {e}")
        if not self._livro_disponivel:
            logger.warning("ProfitDLL: livro de ofertas não registrado - usando só o topo (TinyBook)")
        try:
            self._hist_disponivel = (dll.SetHistoryTradeCallback(cb_hist) == 0
                                     and dll.SetSerieProgressCallback(cb_prog) == 0)
        except Exception as e:      # DLL sem histórico: o gráfico começa na conexão, como antes
            logger.warning(f"Histórico do dia indisponível: {e}")
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
        if self._parar.is_set():
            # stop() já pediu o DLLFinalize: a DLL ainda manda estados ao encerrar, ex. (3,1),
            # que não são falha de login/ativação
            return
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
                # com atualização retida pela taxa, acorda a tempo de entregá-la
                evento = self.fila.get(timeout=max(0.01, self.intervalo_livro) if self._livro_pendente else 0.5)
            except Empty:
                try:
                    self._descarregar_livro()
                except Exception as e:
                    logger.error(f"Erro ao entregar o livro de ofertas: {e}")
                continue
            self._processar_evento(evento)

    def _processar_evento(self, evento: tuple):
        """Despacha um evento da fila (trade, book ou oferta) - sem DLL, testável."""
        try:
            if evento[0] == "trade":
                self._processar_trade(*evento[1:])
            elif evento[0] == "book":
                self._processar_book(*evento[1:])
            elif evento[0] == "offer":      # callback da DLL: giro de iceberg + livro da tela
                self._processar_oferta_bruta(*evento[1:])
            elif evento[0] == "hist_fim":
                self._concluir_historico(evento[1])
            elif evento[0] == "trocar":
                self._executar_troca(evento[1])
            elif evento[0] == "oferta":     # só o livro da tela
                self._processar_oferta(*evento[1:])
            else:
                logger.warning(f"Evento desconhecido na fila da DLL: {evento[0]!r}")
        except Exception as e:
            logger.error(f"Erro ao processar evento da DLL: {e}")

    # ──────────────────────────────────────────────────────────
    # PAPEL ABERTO: troca e histórico do dia (sem DLL, testável)
    # ──────────────────────────────────────────────────────────

    def trocar_ativo(self, ativo: str) -> None:
        """Pede a troca do papel aberto. Quem executa é a thread consumidora (na ordem da fila)."""
        self.fila.put(("trocar", validar_ativo(ativo)))

    def _zerar_livro_tela(self) -> None:
        self.bid = self.ask = None
        self.livro.limpar()
        self._livro_pendente = False
        self._modo_book = None
        self._tiny_visto = False
        self._diverge_desde = None
        self._em_divergencia = False
        self._ultimo_ts_negocio = None

    def _executar_troca(self, ativo: str) -> None:
        """Papel novo: livro da tela e TinyBook passam a ser dele, o livro de ofertas é pedido de novo
        (a DLL manda o FullBook ao assinar) e o histórico do dia é baixado."""
        dll = self.dll
        if dll is None:
            return
        if ativo not in self.papeis:
            if dll.SubscribeTicker(ativo, self.exchange) != 0:
                logger.warning(f"Troca para {ativo}: SubscribeTicker recusado")
                self._sem_historico(ativo, "recusado")
                return
            self.papeis.append(ativo)
            self.assinados += 1
        self.papeis = [ativo] + [p for p in self.papeis if p != ativo]
        self.asset = ativo
        self._zerar_livro_tela()
        sub = getattr(dll, "SubscribeOfferBook", None)
        if sub is not None and ativo not in self.livros_recusados:
            try:
                cancelar = getattr(dll, "UnsubscribeOfferBook", None)
                if cancelar is not None:
                    cancelar(ativo, self.exchange)
                self.livro_ativo = self._livro_disponivel and sub(ativo, self.exchange) == 0
            except Exception as e:
                logger.warning(f"Troca para {ativo}: livro de ofertas falhou: {e}")
                self.livro_ativo = False
        logger.info(f"ProfitDLL: papel aberto agora é {ativo}")
        self.pedir_historico(ativo)

    def pedir_historico(self, ativo: Optional[str] = None) -> bool:
        """Baixa os negócios do pregão de hoje (09:00 até agora) do papel; on_historico recebe tudo de uma vez."""
        ativo = (ativo or self.asset).upper()
        if self.dll is None or not self._hist_disponivel:
            return self._sem_historico(ativo, "indisponivel")
        agora = datetime.now(FUSO_B3)
        inicio = agora.replace(hour=9, minute=0, second=0, microsecond=0)
        if agora <= inicio:
            return self._sem_historico(ativo, "pronto")
        with self._hist_lock:
            self._hist_buffer[ativo] = []
        self.historico = {"ativo": ativo, "progresso": 0, "negocios": 0, "estado": "carregando"}
        ret = self.dll.GetHistoryTrades(ativo, self.exchange, inicio.strftime("%d/%m/%Y %H:%M:%S"),
                                        agora.strftime("%d/%m/%Y %H:%M:%S"))
        if ret != 0:
            logger.warning(f"GetHistoryTrades({ativo}) falhou: código {ret}")
            return self._sem_historico(ativo, "erro")
        return True

    def _sem_historico(self, ativo: str, estado: str) -> bool:
        """Nada a carregar: avisa mesmo assim (lista vazia) para o servidor soltar os negócios ao vivo."""
        self.historico = {"ativo": ativo, "progresso": 100 if estado == "pronto" else 0,
                          "negocios": 0, "estado": estado}
        if self.on_historico:
            try:
                self.on_historico(ativo, [])
            except Exception as e:
                logger.error(f"Erro ao entregar o histórico: {e}")
        return False

    def _concluir_historico(self, ativo: str) -> None:
        with self._hist_lock:
            trades = self._hist_buffer.pop(ativo, [])
        if ativo != self.asset:                       # o usuário já abriu outro papel
            return
        from profitdll.historico import converter_trades      # importado aqui: historico importa a ponte
        codigos = {int(c) for t in trades for c in (t[5], t[6]) if int(c) > 0}
        nomes = {c: self._corretora(c) for c in codigos}
        res = converter_trades(trades, nomes, dia=datetime.now(FUSO_B3).date())
        for t in res.ticks:
            t.asset = ativo
        self.historico = {"ativo": ativo, "progresso": 100, "negocios": len(res.ticks), "estado": "pronto"}
        logger.info(f"Histórico do dia de {ativo}: {len(res.ticks)} negócios "
                    f"({res.ignorados} ignorados, {res.duplicados} duplicados)")
        if self.on_historico:
            try:
                self.on_historico(ativo, res.ticks)
            except Exception as e:
                logger.error(f"Erro ao entregar o histórico: {e}")

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

    def _processar_trade(self, buy, sell, qty, price, ttype, ts, flags=0, numero=None, ativo=""):
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
        tick.asset = (ativo or self.asset).upper()
        self._ultimo_ts_negocio = tick.timestamp
        if self.on_tick:
            try:
                self.on_tick(tick)
            except Exception as e:
                logger.error(f"Erro ao processar tick: {e}")
        if tick.passive_broker:
            lado_pas = "venda" if tick.side == Side.BUY else "compra"
            self._emitir(self._livro_giro.negocio(
                tick.asset, tick.passive_broker, lado_pas, tick.price, tick.qty, tick.timestamp), tick.timestamp)

    def _emitir(self, renovacoes, ts: Optional[float] = None) -> None:
        if not renovacoes or self.on_renovacao is None:
            return
        quando = self._ultimo_ts_negocio if ts is None else ts
        if not quando:
            quando = time.time()
        self.renovacoes_emitidas += len(renovacoes)
        for r in renovacoes:
            try:
                self.on_renovacao(r.ativo, r.corretora, r.lado, r.preco, quando)
            except Exception as e:
                logger.error(f"Erro ao registrar reposição: {e}")

    def _corretora(self, agente: int) -> str:
        if agente <= 0:
            return ""
        return self.nomes.get(agente) or self._nome_agente(agente)

    def _processar_oferta_giro(self, ativo, action, position, side, qty, agent, offer_id, price,
                          has_price, has_qty, has_offer, has_agent, compra, venda, ts):
        """Livro de ofertas → reposição do iceberg. O nome da corretora é resolvido aqui, fora do callback."""
        ativo = (ativo or self.asset).upper()
        c = self.oferta_acoes.setdefault(int(action), [0, 0, 0, 0])
        c[0] += 1
        c[1] += 1 if has_offer and offer_id else 0
        c[2] += 1 if has_agent and agent else 0
        c[3] += 1 if has_price and price else 0
        if action == OFERTA_FULL:
            for blob, lado in ((compra, "compra"), (venda, "venda")):
                if not blob:
                    continue
                ofertas, primeiro, ultimo = decodificar_ofertas(blob)
                chave = (ativo, lado)
                # O livro por posição precisa de TODAS as entradas, inclusive as sem agente/offer_id (que o giro
                # por id descarta): se uma faltar, toda posição seguinte desloca e os giros saem falsos
                try:
                    entradas, _flags = decodifica_array_v2(blob)
                except ValueError:
                    entradas = []
                    self.giro_erros += 1
                if primeiro:
                    self._pacote[chave] = []
                    self._pacote_pos[chave] = []
                buf = self._pacote.setdefault(chave, [])
                buf.extend(ofertas)
                self._pacote_pos.setdefault(chave, []).extend(
                    [float(e[0]), int(e[1]), int(e[2]), int(e[3])] for e in entradas)
                if ultimo:
                    pronto = self._pacote.pop(chave, [])
                    pos = self._livros_pos.setdefault(ativo, LivroPos())
                    novas = self._pacote_pos.pop(chave, [])
                    if lado == "compra":
                        pos.compra = novas
                    else:
                        pos.venda = novas
                    nomeadas = [(oid, preco, qtd, self._corretora(ag))
                                for oid, preco, qtd, ag in pronto]
                    self._emitir(self._livro_giro.definir(ativo, lado, nomeadas, ts), ts)
            return
        if side not in (TINYBOOK_BID, TINYBOOK_ASK):
            return
        lado = "compra" if side == TINYBOOK_BID else "venda"
        pos = self._livros_pos.setdefault(ativo, LivroPos())
        lista = pos.compra if side == TINYBOOK_BID else pos.venda
        # a posição 0 é o fim da lista (mesma convenção do livro da tela, validada ao vivo)
        idx = len(lista) - position - 1
        def _erro(motivo):
            self.giro_erros += 1
            self.giro_erros_motivo[motivo] = self.giro_erros_motivo.get(motivo, 0) + 1
            self.amostra_erro = (self.amostra_erro + [(motivo, ativo, int(action), lado, int(position), len(lista))])[-12:]

        if action == OFERTA_ADD:
            # entra no livro por posição mesmo sem offer_id/agente (senão as posições deslocam)
            if not pos.aplicar(action, position, side, price, qty, agent, offer_id):
                return _erro("add_posicao_invalida")
            if not has_offer or offer_id == 0:
                return
            corretora = self._corretora(agent) if agent else ""
            self._emitir(self._livro_giro.atualizar(ativo, lado, float(price), int(qty), corretora,
                                                    int(offer_id), ts), ts)
            return
        if action not in (OFERTA_EDIT, OFERTA_DELETE, OFERTA_DELETE_FROM):
            return _erro("acao_desconhecida")
        if not 0 <= idx < len(lista):
            return _erro("posicao_fora_da_lista" if lista else "livro_vazio")
        if action == OFERTA_DELETE_FROM:
            afetadas = [list(o) for o in lista[idx:]]
        else:
            afetadas = [list(lista[idx])]
        if action == OFERTA_EDIT:
            self.amostra_edit = (self.amostra_edit + [(ativo, lado, int(position), int(qty), int(lista[idx][1]))])[-12:]
        if not pos.aplicar(action, position, side, price if has_price else 0.0, qty if has_qty else 0,
                           agent if has_agent else 0, offer_id if has_offer else 0):
            return _erro("aplicar_falhou")
        if action == OFERTA_EDIT:
            preco_o, qtd_o, agente_o, oid_o = lista[idx]
            self._emitir(self._livro_giro.atualizar(ativo, lado, float(preco_o), int(qtd_o), self._corretora(agente_o),
                                                    int(oid_o), ts), ts)
            return
        for preco_o, _qtd_o, agente_o, oid_o in afetadas:
            self._emitir(self._livro_giro.atualizar(ativo, lado, float(preco_o), 0, self._corretora(agente_o),
                                                    int(oid_o), ts, apagar=True), ts)

    def _processar_book(self, lado, price, qty, ts_chegada):
        """
        Atualiza o topo do livro (TinyBook) e entrega o snapshot ao engine: o livro de ofertas
        quando está ativo e coerente com o TinyBook, senão o próprio topo (bid + ask).
        Preço ou quantidade <= 0 = lado sem oferta (ex.: leilão).
        O timestamp é o do último negócio (relógio da B3), para não misturar com o relógio
        local; sem negócio ainda, usa a chegada.
        """
        topo = (float(price), int(qty)) if price > 0 and qty > 0 else None
        if lado == TINYBOOK_BID:
            self.bid = topo
        elif lado == TINYBOOK_ASK:
            self.ask = topo
        else:
            return
        self._tiny_visto = True
        self.book_atualizacoes += 1
        self._publicar(ts_chegada, do_tinybook=True)

    # ──────────────────────────────────────────────────────────
    # LIVRO DE OFERTAS (sem DLL, testável)
    # ──────────────────────────────────────────────────────────

    def _processar_oferta_bruta(self, ativo, action, position, side, qty, agent, offer_id, price,
                                has_price, has_qty, has_offer, has_agent, compra, venda, ts):
        """Evento do callback: alimenta o giro de iceberg (todos os papéis) e o livro da tela (o principal)."""
        self._processar_oferta_giro(ativo, action, position, side, qty, agent, offer_id, price,
                                    has_price, has_qty, has_offer, has_agent, compra, venda, ts)
        if (ativo or self.asset).upper() == self.asset:
            self._processar_oferta(action, position, side, float(price) if has_price else 0.0,
                                   int(qty) if has_qty else 0, int(agent) if has_agent else 0,
                                   int(offer_id) if has_offer else 0, venda, compra, ts)

    def _processar_oferta(self, acao, posicao, lado, preco, qtd, agente, offer_id,
                          arr_venda, arr_compra, ts_chegada):
        """Aplica um evento do livro de ofertas no LivroOfertas e entrega (com limite de taxa)."""
        if not self.livro_ativo:
            return
        if acao == AT_FULLBOOK:
            lados = {}
            for nome, bruto in (("venda", arr_venda), ("compra", arr_compra)):
                if bruto is None:
                    lados[nome] = (None, 0)
                    continue
                try:
                    lados[nome] = decodifica_array_v2(bruto)
                except ValueError as e:
                    self.livro.erros += 1
                    logger.warning(f"Livro de ofertas: array {nome} corrompido ({e}) - ignorado")
                    lados[nome] = (None, 0)
            self.livro.full_book(compra=lados["compra"][0], flags_compra=lados["compra"][1],
                                 venda=lados["venda"][0], flags_venda=lados["venda"][1])
        else:
            self.livro.aplicar(acao, posicao, lado, preco, qtd, agente, offer_id)
        self._livro_pendente = True
        self._publicar(ts_chegada)

    def _livro_utilizavel(self, agora: float) -> bool:
        """
        O livro de ofertas vale como book? Precisa estar ativo, ter algum nível e bater com o TinyBook
        (melhor compra e melhor venda). Divergência é tolerada por TOLERANCIA_DIVERGENCIA (latência
        entre os dois canais); passando disso volta ao topo até voltarem a bater.
        """
        if not self.livro_ativo:
            return False
        melhor_c, melhor_v = self.livro.melhor(LADO_COMPRA), self.livro.melhor(LADO_VENDA)
        if melhor_c is None and melhor_v is None:
            return False
        if self._tiny_visto:
            tiny_c = round(self.bid[0], 2) if self.bid else None
            tiny_v = round(self.ask[0], 2) if self.ask else None
            if (tiny_c, tiny_v) != (melhor_c, melhor_v):
                if self._diverge_desde is None:
                    self._diverge_desde = agora
                if agora - self._diverge_desde > TOLERANCIA_DIVERGENCIA:
                    if not self._em_divergencia:
                        self._em_divergencia = True
                        self.livro_divergencias += 1
                        logger.warning(f"Livro de ofertas diverge do TinyBook há mais de "
                                       f"{TOLERANCIA_DIVERGENCIA:g} s - voltando ao topo")
                    return False
                return True
        self._diverge_desde = None
        self._em_divergencia = False
        return True

    def _nome_para(self, codigo: int) -> str:
        """Nome da corretora para o livro: JSON (--agentes) > DLL (em cache) > o código como texto."""
        nome = self.nomes.get(codigo)
        if nome:
            return nome
        if codigo in self._nomes_dll:
            return self._nomes_dll[codigo]
        agora = self._agora()
        if agora - self._nomes_falha.get(codigo, float("-inf")) < 10.0:
            return str(codigo)          # a DLL acabou de não saber: não insiste a cada snapshot
        nome = self._nome_agente(codigo)
        if nome == str(codigo):
            self._nomes_falha[codigo] = agora
        return nome

    def _ts_book(self, ts_chegada: float) -> float:
        """Horário do book: o do último negócio (relógio da B3) para não misturar relógios; senão a chegada."""
        return self._ultimo_ts_negocio if self._ultimo_ts_negocio is not None else ts_chegada

    def _niveis_do_livro(self, ts: float) -> list[BookLevel]:
        """
        Snapshot agregado do livro como BookLevel. O broker fica "" de propósito: o detector de Best
        Offer do engine é alimentado pela corretora do 1º nível a cada snapshot, e aqui o nível tem
        várias corretoras; elas vão em `corretoras`.
        """
        snap = self.livro.snapshot(self.niveis_livro, self._nome_para)
        niveis = []
        for itens, lado in ((snap["bids"], Side.BUY), (snap["asks"], Side.SELL)):
            for n in itens:
                niveis.append(BookLevel(price=n["price"], qty=n["qty"], broker="", side=lado, timestamp=ts,
                                        ordens=n["ordens"], corretoras=n["corretoras"],
                                        fila=n.get("fila", [])))
        return niveis

    def _publicar(self, ts_chegada: Optional[float] = None, do_tinybook: bool = False):
        """
        Entrega o book ao engine. Livro de ofertas utilizável -> snapshot completo, no máximo uma vez a
        cada `intervalo_livro` (o excedente fica pendente e sai em _descarregar_livro). Senão o topo do
        TinyBook, a cada evento dele (como antes do livro de ofertas existir).
        """
        agora = self._agora()
        if ts_chegada is None:
            ts_chegada = time.time()
        ts = self._ts_book(ts_chegada)
        if self._livro_utilizavel(agora):
            if agora - self._ultimo_envio_livro < self.intervalo_livro:
                self._livro_pendente = True
                return
            niveis = self._niveis_do_livro(ts)
            self._ultimo_envio_livro = agora
            self._livro_pendente = False
            self._modo_book = "ofertas"
            self.livro_atualizacoes += 1
        else:
            self._livro_pendente = False
            niveis = topo_para_niveis(self.bid, self.ask, ts)
            if not niveis and not do_tinybook:
                return          # sem topo para entregar: não apaga o book do engine
            self._modo_book = "topo"
        if self.on_book:
            try:
                self.on_book(niveis)
            except Exception as e:
                logger.error(f"Erro ao processar book: {e}")

    def _descarregar_livro(self):
        """
        Chamado quando a fila fica ociosa: entrega a atualização retida pela taxa e reavalia a
        coerência com o TinyBook (volta ao topo / retoma o livro sem esperar o próximo evento).
        """
        if not self.livro_ativo:
            return
        utilizavel = self._livro_utilizavel(self._agora())
        if (utilizavel and (self._livro_pendente or self._modo_book != "ofertas")) \
                or (not utilizavel and self._modo_book == "ofertas"):
            self._publicar()
