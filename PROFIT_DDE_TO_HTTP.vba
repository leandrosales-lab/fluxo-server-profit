' ============================================================
' PROFIT_DDE_TO_HTTP — Macro VBA para Profit Pro → Servidor Python
' ============================================================
' COMO USAR:
'   1. Abra o Excel
'   2. Pressione Alt+F11 para abrir o editor VBA
'   3. Vá em Inserir → Módulo
'   4. Cole todo este código
'   5. Feche o editor VBA
'   6. Habilite referência ao MSXML2:
'      Ferramentas → Referências → marcar "Microsoft XML, v6.0"
'   7. Na planilha, configure as células DDE do Profit:
'      A1: =Profit|Ultima!PETR4       (último preço)
'      B1: =Profit|VolNeg!PETR4       (volume)
'      C1: =Profit|CodAgente!PETR4    (corretora)
'      D1: =Profit|TipNeg!PETR4       (C=compra / V=venda)
'   8. Clique no botão "Iniciar Monitor" ou rode StartMonitor()
' ============================================================

Dim lastPrice As Double
Dim http As Object
Dim isRunning As Boolean

Sub StartMonitor()
    Set http = CreateObject("MSXML2.XMLHTTP")
    isRunning = True
    lastPrice = 0
    Application.OnTime Now + TimeValue("00:00:01"), "CheckAndSend"
    MsgBox "Monitor iniciado! Servidor Python em http://127.0.0.1:5000"
End Sub

Sub StopMonitor()
    isRunning = False
    On Error Resume Next
    Application.OnTime Now + TimeValue("00:00:01"), "CheckAndSend", , False
    MsgBox "Monitor parado."
End Sub

Sub CheckAndSend()
    If Not isRunning Then Exit Sub
    On Error GoTo ErrHandler

    Dim price As Double
    Dim qty As Long
    Dim broker As String
    Dim side As String

    ' Ler valores das células DDE linkadas ao Profit
    price  = CDbl(Cells(1, 1).Value)
    qty    = CLng(Cells(1, 2).Value)
    broker = CStr(Cells(1, 3).Value)
    side   = CStr(Cells(1, 4).Value)

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

        ' Escrever sinal retornado na célula F1
        If http.status = 200 Then
            Cells(1, 6).Value = http.responseText
        End If
    End If

    ' Agendar próxima verificação (1 segundo)
    Application.OnTime Now + TimeValue("00:00:01"), "CheckAndSend"
    Exit Sub

ErrHandler:
    If isRunning Then
        Application.OnTime Now + TimeValue("00:00:05"), "CheckAndSend"
    End If
End Sub
