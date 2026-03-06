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

import sys
import time
import logging
import threading
from typing import Optional, Callable

logger = logging.getLogger("DDEBridge")

# Tentar importar DDE (só Windows via pywin32/pythonwin)
# O módulo 'dde' está em pythonwin/dde.pyd — precisa ser adicionado ao path.
# Fórmula DDE do Profit: =Profit|<Topico>!<Ativo>
#   Servidor (application): "Profit"
#   Tópico (topic):         "Ultima", "VolNeg", "CodAgente", "TipNeg", "QtdNeg" ...
#   Item:                   "PETR4"  (código do ativo)
DDE_OK = False
try:
    import win32ui   # deve ser importado antes do dde
    # Adiciona o diretório pythonwin ao path para encontrar dde.pyd
    import site
    for sp in site.getsitepackages():
        _pw = sp + "\\pythonwin"
        if _pw not in sys.path:
            sys.path.insert(0, _pw)
    import dde as _dde_mod
    DDE_OK = True
except Exception as _e:
    logger.warning(f"DDE não disponível: {_e}. "
                   "Instale pywin32 e certifique-se de estar no Windows.")


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

    # ── Tópicos DDE do Profit Pro para T&T
    # Formato: application="Profit", topic=<campo>, item=<ativo>
    # Equivalente à fórmula Excel: =Profit|<topic>!<item>
    TT_TOPICS = {
        "price":  "Ultima",     # Último preço negociado
        "qty":    "VolNeg",     # Volume do último negócio
        "broker": "CodAgente",  # Código da corretora agente
        "side":   "TipNeg",     # Tipo de negócio: C=compra, V=venda
        "count":  "QtdNeg",     # Contador total de negócios (detecta novo tick)
    }

    # ── Tópicos DDE do Profit Pro para Book de Ofertas (5 níveis)
    # Baseado na documentação DDE do Profit/Nelogica.
    # Verificar nomes exatos na versão instalada do Profit.
    BOOK_TOPICS: list[dict] = []
    for _i in range(1, 6):
        BOOK_TOPICS += [
            {"side": "C", "field": "price",  "topic": f"OfertaCompraPrc{_i}"},
            {"side": "C", "field": "qty",    "topic": f"OfertaCompraQtd{_i}"},
            {"side": "C", "field": "broker", "topic": f"OfertaCompraAgt{_i}"},
            {"side": "V", "field": "price",  "topic": f"OfertaVendaPrc{_i}"},
            {"side": "V", "field": "qty",    "topic": f"OfertaVendaQtd{_i}"},
            {"side": "V", "field": "broker", "topic": f"OfertaVendaAgt{_i}"},
        ]

    def __init__(self, asset: str, poll_interval: float = 0.5):
        self.asset         = asset.upper()
        self.poll_interval = poll_interval
        self._running      = False
        self._thread: Optional[threading.Thread] = None
        self._server_name  = "Profit"   # Nome do servidor DDE do Profit Pro

        # Callbacks → FlowEngine
        self.on_tick: Optional[Callable] = None
        self.on_book: Optional[Callable] = None

        # Controle de negócios já processados
        self._last_trade_count = -1
        self._last_price       = None

        # Servidor DDE local (necessário para criar conversas como cliente)
        self._dde_server = None

        # Cache de conversas DDE: {topic → conversation}
        self._conversations: dict = {}

    def start(self) -> bool:
        if not DDE_OK:
            logger.error("DDE não disponível — instale pywin32 no Windows")
            return False
        try:
            self._dde_server = _dde_mod.CreateServer()
            self._dde_server.Create("FluxoServerDDEClient")
        except Exception as e:
            logger.error(f"Falha ao criar servidor DDE local: {e}")
            return False
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"DDEBridge iniciado para {self.asset} | Servidor Profit DDE: '{self._server_name}'")
        return True

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._conversations.clear()
        if self._dde_server:
            try:
                self._dde_server.Destroy()
            except Exception:
                pass
            self._dde_server = None
        logger.info("DDEBridge encerrado")

    def _dde_request(self, topic: str, item: str) -> Optional[str]:
        """Solicita um valor via DDE.

        No Profit Pro, o formato é:
          application = "Profit"
          topic       = nome do campo (ex: "Ultima", "VolNeg")
          item        = código do ativo (ex: "PETR4")
        """
        try:
            if topic not in self._conversations:
                conv = _dde_mod.CreateConversation(self._dde_server)
                conv.ConnectTo(self._server_name, topic)
                self._conversations[topic] = conv
            value = self._conversations[topic].Request(item)
            return str(value).strip() if value else None
        except Exception:
            # Descarta a conversa com falha para reconectar na próxima tentativa
            self._conversations.pop(topic, None)
            return None

    def _read_tt(self):
        """Lê o último negócio do T&T via DDE.

        No Profit Pro cada campo é um tópico separado; o item é o código do ativo.
        Equivalente às fórmulas Excel:
          =Profit|QtdNeg!PETR4   (contador de negócios)
          =Profit|Ultima!PETR4   (último preço)
          =Profit|VolNeg!PETR4   (volume do negócio)
          =Profit|CodAgente!PETR4 (corretora)
          =Profit|TipNeg!PETR4   (C=compra / V=venda)
        """
        try:
            trade_count_s = self._dde_request(self.TT_TOPICS["count"], self.asset)
            if not trade_count_s:
                return
            trade_count = int(trade_count_s.replace(".", "").replace(",", ""))
            if trade_count == self._last_trade_count:
                return  # Nenhum negócio novo
            self._last_trade_count = trade_count

            price_s  = self._dde_request(self.TT_TOPICS["price"],  self.asset)
            qty_s    = self._dde_request(self.TT_TOPICS["qty"],    self.asset)
            broker_s = self._dde_request(self.TT_TOPICS["broker"], self.asset)
            side_s   = self._dde_request(self.TT_TOPICS["side"],   self.asset)

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
        """Lê os 5 primeiros níveis do Book via DDE.

        Os tópicos para o book variam por versão do Profit.
        Verificar em: Profit > Ferramentas > DDE > Itens disponíveis.
        Nomes comuns: OfertaCompraPrc1, OfertaVendaPrc1, etc.
        """
        levels = []
        buy_rows: dict[int, dict] = {}
        sell_rows: dict[int, dict] = {}

        try:
            for i, bt in enumerate(self.BOOK_TOPICS):
                value = self._dde_request(bt["topic"], self.asset)
                if not value:
                    continue
                level_idx = i // 6 + 1
                row_dict  = buy_rows if bt["side"] == "C" else sell_rows
                if level_idx not in row_dict:
                    row_dict[level_idx] = {"side": bt["side"], "price": None, "qty": None, "broker": ""}

                if bt["field"] == "price":
                    row_dict[level_idx]["price"] = float(value.replace(",", "."))
                elif bt["field"] == "qty":
                    row_dict[level_idx]["qty"] = int(value.replace(".", "").replace(",", ""))
                elif bt["field"] == "broker":
                    row_dict[level_idx]["broker"] = value.strip().upper()

            for row_dict in (buy_rows, sell_rows):
                for row in row_dict.values():
                    if row["price"] and row["qty"]:
                        levels.append(row)

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
