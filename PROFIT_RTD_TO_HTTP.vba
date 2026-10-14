' ============================================================
' PROFIT_RTD_TO_HTTP — Macro VBA standalone para Profit Pro RTD → Servidor Python
' ============================================================
' VERSAO SIMPLIFICADA (sem integracao NTSL via celulas A1:D1)
' Para versao completa com bridge NTSL, use excel/FLUXO_BRIDGE_RTD.bas
'
' Envia o retrato BRUTO do RTD para POST /rtd; o servidor Python infere
' quantidade (diferenca do volume acumulado) e lado agressor.
'
' COMO USAR:
'   1. Abra o Excel
'   2. Pressione Alt+F11 para abrir o editor VBA
'   3. Va em Inserir → Modulo
'   4. Cole todo este codigo
'   5. Feche o editor VBA
'   6. No Profit: Ferramentas > Exportar em Tempo Real > RTD
'   7. Na planilha, insira as formulas RTD:
'      A1: =RTD("rtdtrading.rtdserver";;"PETR4_B_0";"ULT")  (ultimo preco)
'      B1: =RTD("rtdtrading.rtdserver";;"PETR4_B_0";"QTT")  (quantidade acumulada; VOL e' R$)
'      C1: =RTD("rtdtrading.rtdserver";;"PETR4_B_0";"ACP")  (agente compra)
'      D1: =RTD("rtdtrading.rtdserver";;"PETR4_B_0";"AVD")  (agente venda)
'      E1: =RTD("rtdtrading.rtdserver";;"PETR4_B_0";"NEG")  (num negocios)
'
'   SUFIXOS: _B_0 = Bovespa (acoes) | _F_0 = BMF (futuros, ex.: WDOFUT_F_0)
'
'   8. Rode StartMonitor() (Alt+F8)
' ============================================================

Dim isRunning As Boolean
Dim lastVol As Double
Dim lastNeg As Double

Sub StartMonitor()
    Application.RTD.ThrottleInterval = 0   ' padrao do Excel agrupa a cada 2s
    isRunning = True
    lastVol = -1
    lastNeg = -1
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

    Dim price As Double, vol As Double, neg As Double
    price = Numero(Cells(1, 1))
    vol = Numero(Cells(1, 2))
    neg = Numero(Cells(1, 5))

    If price > 0 And (vol <> lastVol Or neg <> lastNeg) Then
        lastVol = vol
        lastNeg = neg

        ' Str() usa sempre ponto decimal (Format() usaria virgula em pt-BR)
        Dim body As String
        body = "{""price"":" & Trim(Str(price)) & _
               ",""volume"":" & Trim(Str(vol)) & _
               ",""trades"":" & Trim(Str(neg)) & _
               ",""buyer"":""" & Replace(Cells(1, 3).Text, """", "") & """" & _
               ",""seller"":""" & Replace(Cells(1, 4).Text, """", "") & """}"

        Dim http As Object
        Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
        http.Open "POST", "http://127.0.0.1:5000/rtd", False
        http.setRequestHeader "Content-Type", "application/json"
        http.Send body

        ' Mostrar sinal retornado na celula G1
        If http.Status = 200 Then
            Cells(1, 7).Value = http.responseText
        End If
    End If

    Application.OnTime Now + TimeValue("00:00:01"), "CheckAndSend"
    Exit Sub

ErrHandler:
    If isRunning Then
        Application.OnTime Now + TimeValue("00:00:05"), "CheckAndSend"
    End If
End Sub

Function Numero(c As Range) As Double
    If IsError(c.Value) Then Exit Function
    If IsNumeric(c.Value) Then Numero = CDbl(c.Value)
End Function
