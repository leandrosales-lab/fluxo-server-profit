Attribute VB_Name = "FLUXO_BRIDGE"
' ============================================================
' FLUXO BRIDGE — Macro VBA para Excel
' ============================================================
' Intermediário entre o Profit Pro (DDE) e o servidor Python
'
' ARQUITETURA:
'   Profit DDE  →  Células E1:I1 (fórmulas DDE)
'   VBA Timer   →  Lê E1:I1, envia POST ao servidor Python
'   Servidor    →  Retorna sinal (A1), confiança (B1), preço (C1), stop (D1)
'   NTSL Robot  →  Lê A1:D1 via parâmetros DDE linkados ao Excel
'
' CÉLULAS DO EXCEL:
'   A1 = iSinalExterno    (1=BUY, -1=SELL, 0=WAIT, 2=CLOSE)
'   B1 = fConfiancaSinal  (0.0 a 1.0)
'   C1 = fPrecoSinal      (preço do sinal)
'   D1 = fStopSinal       (stop do sinal)
'   E1 = LastPrice  via DDE do Profit (=Profit|Ultima!PETR4)
'   F1 = LastQty    via DDE do Profit (=Profit|VolNeg!PETR4)
'   G1 = LastBroker via DDE do Profit (=Profit|CodAgente!PETR4)
'   H1 = LastSide   via DDE do Profit (=Profit|TipNeg!PETR4)
'   I1 = TradeCount via DDE do Profit (=Profit|QtdNeg!PETR4)
'
' SETUP NO EXCEL:
'   1. Inserir as fórmulas DDE nas células E1:I1
'   2. No Profit: menu Ferramentas > DDE > habilitar servidor DDE
'   3. Rodar macro IniciarBridge()
'   4. Linkar parâmetros do robô NTSL às células A1:D1 via DDE Excel
'
' USO NO NTSL (Profit):
'   iSinalExterno  → link DDE para esta planilha, célula A1
'   fConfiancaSinal → link DDE para esta planilha, célula B1
'   fPrecoSinal    → link DDE para esta planilha, célula C1
'   fStopSinal     → link DDE para esta planilha, célula D1
' ============================================================

Option Explicit

' ── Configurações
Private Const PYTHON_URL As String = "http://127.0.0.1:5000"
Private Const ASSET As String = "PETR4"
Private Const INTERVAL_MS As Long = 500   ' intervalo de polling em ms

' ── Estado interno
Private mTimer As Long
Private mUltimoTradeCount As Long
Private mRodando As Boolean

' ============================================================
' IniciarBridge — inicia o timer de polling
' ============================================================
Public Sub IniciarBridge()
    If mRodando Then
        MsgBox "Bridge já está rodando.", vbInformation
        Exit Sub
    End If

    mUltimoTradeCount = 0
    mRodando = True
    mTimer = Application.OnTime(Now + TimeValue("00:00:01"), "VerificarEEnviar", , True)

    ' Inicializar células de saída
    With ThisWorkbook.Sheets(1)
        .Cells(1, 1).Value = 0   ' iSinalExterno = WAIT
        .Cells(1, 2).Value = 0   ' fConfiancaSinal
        .Cells(1, 3).Value = 0   ' fPrecoSinal
        .Cells(1, 4).Value = 0   ' fStopSinal
    End With

    MsgBox "Fluxo Bridge iniciado! Servidor Python: " & PYTHON_URL, vbInformation
End Sub

' ============================================================
' PararBridge — para o timer
' ============================================================
Public Sub PararBridge()
    mRodando = False
    On Error Resume Next
    Application.OnTime Now + TimeValue("00:00:01"), "VerificarEEnviar", , False
    On Error GoTo 0

    ' Limpar sinal
    With ThisWorkbook.Sheets(1)
        .Cells(1, 1).Value = 0
        .Cells(1, 2).Value = 0
        .Cells(1, 3).Value = 0
        .Cells(1, 4).Value = 0
    End With

    MsgBox "Fluxo Bridge parado.", vbInformation
End Sub

' ============================================================
' VerificarEEnviar — loop principal (chamado pelo timer)
' ============================================================
Public Sub VerificarEEnviar()
    If Not mRodando Then Exit Sub

    Dim ws As Worksheet
    Set ws = ThisWorkbook.Sheets(1)

    ' ── Ler dados DDE do Profit (células E1:I1)
    Dim dLastPrice As Double
    Dim iLastQty As Long
    Dim sLastBroker As String
    Dim sLastSide As String
    Dim iTradeCount As Long

    On Error Resume Next
    dLastPrice = CDbl(ws.Cells(1, 5).Value)   ' E1 = Ultima
    iLastQty = CLng(ws.Cells(1, 6).Value)     ' F1 = Volume negociado
    sLastBroker = CStr(ws.Cells(1, 7).Value)  ' G1 = Cod. Agente
    sLastSide = CStr(ws.Cells(1, 8).Value)    ' H1 = Tipo negócio (C/V)
    iTradeCount = CLng(ws.Cells(1, 9).Value)  ' I1 = Qtd negócios
    On Error GoTo 0

    ' ── Enviar tick ao servidor Python somente se houve novo negócio
    If iTradeCount > mUltimoTradeCount And dLastPrice > 0 Then
        mUltimoTradeCount = iTradeCount

        ' Montar JSON do tick
        Dim sTickJSON As String
        sTickJSON = "{""price"":" & Format(dLastPrice, "0.00") & _
                    ",""qty"":" & iLastQty & _
                    ",""broker"":""" & sLastBroker & """" & _
                    ",""side"":""" & sLastSide & """}"

        ' Enviar POST /tick
        EnviarPOST PYTHON_URL & "/tick", sTickJSON

        ' ── Consultar sinal atual (GET /signal)
        Dim sSinal As String
        sSinal = FazerGET(PYTHON_URL & "/signal")

        If sSinal <> "" Then
            ' Parsear campos do JSON de resposta
            Dim sSinalVal As String
            Dim dConf As Double
            Dim dPreco As Double
            Dim dStop As Double

            sSinalVal = ExtrairStr(sSinal, """signal"":""", """")
            dConf = CDbl(ExtrairStr(sSinal, """confidence"":", ","))
            dPreco = CDbl(ExtrairStr(sSinal, """price"":", ","))
            dStop = CDbl(ExtrairStr(sSinal, """stop_price"":", ","))


            ' Converter sinal texto → código numérico para NTSL
            Dim iSinalNum As Integer
            Select Case UCase(sSinalVal)
                Case "BUY":   iSinalNum = 1
                Case "SELL":  iSinalNum = -1
                Case "CLOSE": iSinalNum = 2
                Case Else:    iSinalNum = 0   ' WAIT
            End Select

            ' Gravar nas células de saída (lidas pelo robô NTSL via DDE)
            ws.Cells(1, 1).Value = iSinalNum  ' A1 = iSinalExterno
            ws.Cells(1, 2).Value = dConf      ' B1 = fConfiancaSinal
            ws.Cells(1, 3).Value = dPreco     ' C1 = fPrecoSinal
            ws.Cells(1, 4).Value = dStop      ' D1 = fStopSinal
        End If
    End If

    ' Reagendar próxima execução
    If mRodando Then
        Application.OnTime Now + TimeSerial(0, 0, 0) + INTERVAL_MS / 86400000#, _
                            "VerificarEEnviar", , True
    End If
End Sub

' ============================================================
' EnviarPOST — faz HTTP POST com WinHTTP
' ============================================================
Private Sub EnviarPOST(sURL As String, sBody As String)
    On Error GoTo ErrHandler
    Dim oHTTP As Object
    Set oHTTP = CreateObject("WinHttp.WinHttpRequest.5.1")
    oHTTP.Open "POST", sURL, False
    oHTTP.SetRequestHeader "Content-Type", "application/json"
    oHTTP.Send sBody
    Exit Sub
ErrHandler:
    ' Silencioso: servidor pode não estar ativo
End Sub

' ============================================================
' FazerGET — faz HTTP GET e retorna o corpo da resposta
' ============================================================
Private Function FazerGET(sURL As String) As String
    On Error GoTo ErrHandler
    Dim oHTTP As Object
    Set oHTTP = CreateObject("WinHttp.WinHttpRequest.5.1")
    oHTTP.Open "GET", sURL, False
    oHTTP.Send
    If oHTTP.Status = 200 Then
        FazerGET = oHTTP.ResponseText
    Else
        FazerGET = ""
    End If
    Exit Function
ErrHandler:
    FazerGET = ""
End Function

' ============================================================
' ExtrairStr — extrai valor entre dois delimitadores num JSON
' ============================================================
Private Function ExtrairStr(sJSON As String, sIni As String, sFim As String) As String
    Dim iPosIni As Long, iPosFim As Long
    iPosIni = InStr(sJSON, sIni)
    If iPosIni = 0 Then Exit Function
    iPosIni = iPosIni + Len(sIni)
    iPosFim = InStr(iPosIni, sJSON, sFim)
    If iPosFim = 0 Then Exit Function
    ExtrairStr = Mid(sJSON, iPosIni, iPosFim - iPosIni)
End Function
