"""
DDE BRIDGE — Integração com Profit Pro via DDE
===============================================
O Profit Pro suporta DDE (Dynamic Data Exchange) para exportar
dados em tempo real para planilhas e aplicativos externos.

Esta ponte:
  1. Lê Book e T&T do Profit via DDE (servidor DDE do Profit)
  2. Envia ao FlowEngine para análise
  3. Expõe os sinais via HTTP para o robô NTSL consultar

Configuração no Profit:
  - Times & Trades → Exportar via DDE ativo
  - Book de Ofertas → Exportar via DDE ativo

OBS: DDE só funciona no Windows.
Em Linux/Mac, use o modo OCR (screen_reader.py) ou o modo de
injeção manual via API POST /tick e /book.

Requisito Windows: pip install pywin32
"""

import time
import logging
import threading
from typing import Optional, Callable

logger = logging.getLogger("DDEBridge")

# Tentar importar DDE (só Windows)
try:
    import win32dde
    DDE_OK = True
except ImportError:
    DDE_OK = False
    logger.warning("pywin32 não instalado — DDE desativado. "
                   "Use: pip install pywin32 (apenas Windows)")


class DDEBridge:
    """
    Lê dados do Profit Pro via DDE e alimenta o FlowEngine.

    Tópicos DDE típicos do Profit:
      Servidor: "ProfitChart"
      Tópico T&T:  "TimesAndTrades|ATIVO"
      Tópico Book: "BookOffers|ATIVO"

    Itens disponíveis variam por versão do Profit.
    Verificar na documentação DDE do Profit/Nelogica.
    """

    # ── Itens DDE do Times & Trades
    TT_ITEMS = [
        "LastPrice",      # Último preço negociado
        "LastQty",        # Última quantidade negociada
        "LastBroker",     # Corretora do último negócio
        "LastSide",       # Lado do último negócio (C/V)
        "TradeCount",     # Contador de negócios (detectar novo negócio)
    ]

    # ── Itens DDE do Book (5 primeiros níveis)
    BOOK_ITEMS = []
    for i in range(1, 6):
        BOOK_ITEMS += [
            f"BidPrice{i}",   # Preço de compra nível i
            f"BidQty{i}",     # Quantidade de compra nível i
            f"BidBroker{i}",  # Corretora compra nível i
            f"AskPrice{i}",   # Preço de venda nível i
            f"AskQty{i}",     # Quantidade de venda nível i
            f"AskBroker{i}",  # Corretora venda nível i
        ]

    def __init__(self, asset: str, poll_interval: float = 0.5):
        self.asset         = asset.upper()
        self.poll_interval = poll_interval
        self._running      = False
        self._thread: Optional[threading.Thread] = None
        self._server_name  = "ProfitChart"

        # Callbacks → FlowEngine
        self.on_tick: Optional[Callable] = None
        self.on_book: Optional[Callable] = None

        # Controle de negócios já processados
        self._last_trade_count = -1
        self._last_price       = None

        # Cache de conversas DDE (evita abrir/fechar nova conexão a cada request)
        self._conversations: dict = {}

    def start(self) -> bool:
        if not DDE_OK:
            logger.error("DDE não disponível — instale pywin32 no Windows")
            return False
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"DDEBridge iniciado para {self.asset}")
        return True

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._conversations.clear()
        logger.info("DDEBridge encerrado")

    def _dde_request(self, topic: str, item: str) -> Optional[str]:
        """Solicita um valor via DDE, reutilizando a conversa já aberta para o tópico."""
        try:
            if topic not in self._conversations:
                conv = win32dde.CreateConversation(None)
                conv.ConnectTo(self._server_name, topic)
                self._conversations[topic] = conv
            value = self._conversations[topic].Request(item)
            return str(value).strip() if value else None
        except Exception:
            # Descarta a conversa com falha para reconectar na próxima tentativa
            self._conversations.pop(topic, None)
            return None

    def _read_tt(self):
        """Lê o último negócio do T&T via DDE."""
        topic = f"TimesAndTrades|{self.asset}"
        try:
            trade_count_s = self._dde_request(topic, "TradeCount")
            if not trade_count_s:
                return
            trade_count = int(trade_count_s)
            if trade_count == self._last_trade_count:
                return  # Nenhum negócio novo
            self._last_trade_count = trade_count

            price_s  = self._dde_request(topic, "LastPrice")
            qty_s    = self._dde_request(topic, "LastQty")
            broker_s = self._dde_request(topic, "LastBroker")
            side_s   = self._dde_request(topic, "LastSide")

            if not all([price_s, qty_s]):
                return

            price  = float(price_s.replace(",", "."))
            qty    = int(qty_s.replace(".", "").replace(",", ""))
            broker = (broker_s or "").strip().upper()
            side   = "C" if (side_s or "").strip().upper() in ("C", "COMPRA", "BUY") else "V"

            if self.on_tick:
                self.on_tick({
                    "price": price, "qty": qty,
                    "broker": broker, "side": side,
                    "timestamp": time.time()
                })

        except Exception as e:
            logger.debug(f"Erro ao ler T&T via DDE: {e}")

    def _read_book(self):
        """Lê os 5 primeiros níveis do Book via DDE."""
        topic = f"BookOffers|{self.asset}"
        levels = []
        try:
            for i in range(1, 6):
                # Bid (compra)
                bid_p = self._dde_request(topic, f"BidPrice{i}")
                bid_q = self._dde_request(topic, f"BidQty{i}")
                bid_b = self._dde_request(topic, f"BidBroker{i}")
                if bid_p and bid_q:
                    levels.append({
                        "price":  float(bid_p.replace(",", ".")),
                        "qty":    int(bid_q.replace(".", "").replace(",", "")),
                        "broker": (bid_b or "").strip().upper(),
                        "side":   "C"
                    })

                # Ask (venda)
                ask_p = self._dde_request(topic, f"AskPrice{i}")
                ask_q = self._dde_request(topic, f"AskQty{i}")
                ask_b = self._dde_request(topic, f"AskBroker{i}")
                if ask_p and ask_q:
                    levels.append({
                        "price":  float(ask_p.replace(",", ".")),
                        "qty":    int(ask_q.replace(".", "").replace(",", "")),
                        "broker": (ask_b or "").strip().upper(),
                        "side":   "V"
                    })

            if levels and self.on_book:
                self.on_book(levels)

        except Exception as e:
            logger.debug(f"Erro ao ler Book via DDE: {e}")

    def _loop(self):
        while self._running:
            try:
                self._read_tt()
                self._read_book()
            except Exception as e:
                logger.error(f"Erro no loop DDE: {e}")
            time.sleep(self.poll_interval)


# ──────────────────────────────────────────────────────────────
# ALTERNATIVA: Injeção via Planilha Excel + DDE
# ──────────────────────────────────────────────────────────────

EXCEL_VBA_TEMPLATE = '''
' ============================================================
' PROFIT_DDE_TO_HTTP.xlsm — Macro VBA para pontar Profit → Servidor Python
' ============================================================
' Cole este código em um módulo do Excel (Alt+F11 → Inserir → Módulo)
' Configure o Profit para enviar DDE para o Excel,
' e esta macro repassa os dados ao servidor Python via HTTP.
'
' CONFIGURAÇÃO:
'   1. Coluna A: Preço do T&T (célula A1 = Profit DDE link)
'   2. Coluna B: Quantidade
'   3. Coluna C: Corretora
'   4. Coluna D: Lado (C/V)
'   5. Coluna E: Preço Book Bid 1
'   ... etc
'
' Habilitar referência ao MSXML2: Ferramentas → Referências → Microsoft XML
' ============================================================

Dim lastPrice As Double
Dim http As Object

Sub StartMonitor()
    Set http = CreateObject("MSXML2.XMLHTTP")
    Application.OnTime Now + TimeValue("00:00:01"), "CheckAndSend"
    MsgBox "Monitor iniciado! Servidor: http://127.0.0.1:5000"
End Sub

Sub CheckAndSend()
    On Error GoTo ErrHandler
    
    Dim price As Double
    Dim qty As Long
    Dim broker As String
    Dim side As String
    
    ' Ler valores das células linkadas ao Profit DDE
    price  = Cells(1, 1).Value   ' =\'ProfitChart\'|\'TimesAndTrades|PETR4\'!LastPrice
    qty    = Cells(1, 2).Value   ' =\'ProfitChart\'|\'TimesAndTrades|PETR4\'!LastQty
    broker = Cells(1, 3).Value   ' =\'ProfitChart\'|\'TimesAndTrades|PETR4\'!LastBroker
    side   = Cells(1, 4).Value   ' =\'ProfitChart\'|\'TimesAndTrades|PETR4\'!LastSide
    
    ' Enviar apenas se preço mudou (novo negócio)
    If price <> lastPrice And price > 0 And qty > 0 Then
        lastPrice = price
        
        Dim body As String
        body = "{""price"":" & price & ","
        body = body & """qty"":" & qty & ","
        body = body & """broker"":""" & broker & ""","
        body = body & """side"":""" & side & """}"
        
        http.Open "POST", "http://127.0.0.1:5000/tick", False
        http.setRequestHeader "Content-Type", "application/json"
        http.send body
        
        ' Ler sinal retornado
        If http.status = 200 Then
            Dim resp As String
            resp = http.responseText
            ' Mostrar sinal na célula F1 (opcional)
            ' Cells(1, 6).Value = resp
        End If
    End If
    
    ' Agendar próxima verificação (1 segundo)
    Application.OnTime Now + TimeValue("00:00:01"), "CheckAndSend"
    Exit Sub
    
ErrHandler:
    Application.OnTime Now + TimeValue("00:00:05"), "CheckAndSend"
End Sub

Sub StopMonitor()
    On Error Resume Next
    Application.OnTime Now + TimeValue("00:00:01"), "CheckAndSend", , False
    MsgBox "Monitor parado."
End Sub
'''

def save_vba_template(path: str = "PROFIT_DDE_TO_HTTP.vba"):
    """Salva o template VBA para uso no Excel."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(EXCEL_VBA_TEMPLATE)
    logger.info(f"Template VBA salvo em: {path}")
