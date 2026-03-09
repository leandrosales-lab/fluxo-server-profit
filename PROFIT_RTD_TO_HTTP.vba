' ============================================================
' PROFIT_RTD_TO_HTTP — Macro VBA standalone para Profit Pro RTD → Servidor Python
' ============================================================
' VERSAO SIMPLIFICADA (sem integracao NTSL via celulas A1:D1)
' Para versao completa com bridge NTSL, use excel/FLUXO_BRIDGE_RTD.bas
'
' COMO USAR:
'   1. Abra o Excel
'   2. Pressione Alt+F11 para abrir o editor VBA
'   3. Va em Inserir → Modulo
'   4. Cole todo este codigo
'   5. Feche o editor VBA
'   6. No Profit: Ferramentas > Exportar em Tempo Real > RTD
'   7. Na planilha, insira as formulas RTD:
'      A1: =RTD("rtdtrading.rtdserver";;"PETR4_F_0";"ULT")  (ultimo preco)
'      B1: =RTD("rtdtrading.rtdserver";;"PETR4_F_0";"VOL")  (volume)
'      C1: =RTD("rtdtrading.rtdserver";;"PETR4_F_0";"ACP")  (agente compra)
'      D1: =RTD("rtdtrading.rtdserver";;"PETR4_F_0";"AVD")  (agente venda)
'      E1: =RTD("rtdtrading.rtdserver";;"PETR4_F_0";"NEG")  (num negocios)
'
'   SUFIXOS: _F_0 = Bovespa (acoes) | _B_0 = BMF (futuros)
'
'   8. Rode StartMonitor() (Alt+F8)
' ============================================================

Dim lastTradeCount As Long
Dim http As Object
Dim isRunning As Boolean

Sub StartMonitor()
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    isRunning = True
    lastTradeCount = 0
    Application.OnTime Now + TimeValue("00:00:01"), "CheckAndSend"
    MsgBox "Monitor RTD iniciado! Servidor Python em http://127.0.0.1:5000"
End Sub

Sub StopMonitor()
    isRunning = False
    On Error Resume Next
    Application.OnTime Now + TimeValue("00:00:01"), "CheckAndSend", , False
    MsgBox "Monitor RTD parado."
End Sub

Sub CheckAndSend()
    If Not isRunning Then Exit Sub
    On Error GoTo ErrHandler

    Dim price As Double
    Dim vol As Double
    Dim brokerBuy As String
    Dim brokerSell As String
    Dim tradeCount As Long

    ' Ler valores das celulas RTD linkadas ao Profit
    price = CDbl(Cells(1, 1).Value)        ' A1 = ULT
    vol = CDbl(Cells(1, 2).Value)          ' B1 = VOL
    brokerBuy = CStr(Cells(1, 3).Value)    ' C1 = ACP
    brokerSell = CStr(Cells(1, 4).Value)   ' D1 = AVD
    tradeCount = CLng(Cells(1, 5).Value)   ' E1 = NEG

    ' Enviar apenas se houve novo negocio
    If tradeCount > lastTradeCount And price > 0 Then
        lastTradeCount = tradeCount

        Dim body As String
        body = "{""price"":" & Format(price, "0.00") & ","
        body = body & """qty"":" & Format(vol, "0") & ","
        body = body & """broker"":""" & brokerBuy & ""","
        body = body & """broker_sell"":""" & brokerSell & ""","
        body = body & """side"":""N""}"

        http.Open "POST", "http://127.0.0.1:5000/tick", False
        http.setRequestHeader "Content-Type", "application/json"
        http.Send body

        ' Mostrar sinal retornado na celula G1
        If http.Status = 200 Then
            Cells(1, 7).Value = http.responseText
        End If
    End If

    ' Agendar proxima verificacao (1 segundo)
    Application.OnTime Now + TimeValue("00:00:01"), "CheckAndSend"
    Exit Sub

ErrHandler:
    If isRunning Then
        Application.OnTime Now + TimeValue("00:00:05"), "CheckAndSend"
    End If
End Sub
