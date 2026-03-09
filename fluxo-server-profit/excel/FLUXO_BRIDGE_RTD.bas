Attribute VB_Name = "FLUXO_BRIDGE_RTD"
' ============================================================
' FLUXO BRIDGE RTD — Macro VBA para Excel (usa RTD do Profit)
' ============================================================
' Intermediario entre o Profit Pro (RTD) e o servidor Python
'
' DIFERENCA DO DDE:
'   RTD e mais estavel e recomendado pela Nelogica.
'   Usa =RTD("rtdtrading.rtdserver";; "ATIVO_F_0"; "CAMPO")
'   Nao requer ativar servidor DDE no Profit.
'
' ARQUITETURA:
'   Profit RTD  ->  Celulas E1:I1 (formulas RTD)
'   VBA Timer   ->  Le E1:I1, envia POST ao servidor Python
'   Servidor    ->  Retorna sinal (A1), confianca (B1), preco (C1), stop (D1)
'   NTSL Robot  ->  Le A1:D1 via parametros DDE linkados ao Excel
'
' CELULAS DO EXCEL:
'   A1 = iSinalExterno    (1=BUY, -1=SELL, 0=WAIT, 2=CLOSE)
'   B1 = fConfiancaSinal  (0.0 a 1.0)
'   C1 = fPrecoSinal      (preco do sinal)
'   D1 = fStopSinal       (stop do sinal)
'   E1 = ULT   via RTD do Profit (ultimo preco)
'   F1 = VOL   via RTD do Profit (volume)
'   G1 = ACP   via RTD do Profit (agente comprador)
'   H1 = AVD   via RTD do Profit (agente vendedor)
'   I1 = NEG   via RTD do Profit (numero de negocios)
'
' FORMULAS RTD (inserir manualmente nas celulas):
'   E1 = =RTD("rtdtrading.rtdserver";;"PETR4_F_0";"ULT")
'   F1 = =RTD("rtdtrading.rtdserver";;"PETR4_F_0";"VOL")
'   G1 = =RTD("rtdtrading.rtdserver";;"PETR4_F_0";"ACP")
'   H1 = =RTD("rtdtrading.rtdserver";;"PETR4_F_0";"AVD")
'   I1 = =RTD("rtdtrading.rtdserver";;"PETR4_F_0";"NEG")
'
' SUFIXOS DO ATIVO:
'   _F_0 = Bovespa (acoes: PETR4, VALE3, etc.)
'   _B_0 = BMF (futuros: DOLFUT, WINFUT, etc.)
'
' SETUP:
'   1. Inserir as formulas RTD nas celulas E1:I1
'   2. No Profit: menu Ferramentas > Exportar em Tempo Real > RTD
'   3. Rodar macro IniciarBridge()
'   4. Linkar parametros do robo NTSL as celulas A1:D1 via DDE Excel
' ============================================================

Option Explicit

' -- Configuracoes
Private Const PYTHON_URL As String = "http://127.0.0.1:5000"
Private Const ASSET As String = "PETR4"
Private Const INTERVAL_MS As Long = 500   ' intervalo de polling em ms

' -- Estado interno
Private mUltimoTradeCount As Long
Private mRodando As Boolean

' ============================================================
' IniciarBridge — inicia o timer de polling
' ============================================================
Public Sub IniciarBridge()
    If mRodando Then
        MsgBox "Bridge ja esta rodando.", vbInformation
        Exit Sub
    End If

    mUltimoTradeCount = 0
    mRodando = True

    ' Inicializar celulas de saida
    With ThisWorkbook.Sheets(1)
        .Cells(1, 1).Value = 0   ' iSinalExterno = WAIT
        .Cells(1, 2).Value = 0   ' fConfiancaSinal
        .Cells(1, 3).Value = 0   ' fPrecoSinal
        .Cells(1, 4).Value = 0   ' fStopSinal
    End With

    ' Agendar primeira execucao
    Application.OnTime Now + TimeSerial(0, 0, 1), "VerificarEEnviarRTD"

    MsgBox "Fluxo Bridge RTD iniciado!" & vbCrLf & _
           "Servidor Python: " & PYTHON_URL & vbCrLf & vbCrLf & _
           "Certifique-se de que:" & vbCrLf & _
           "  1. As formulas RTD estao em E1:I1" & vbCrLf & _
           "  2. O Profit Pro esta aberto com RTD habilitado" & vbCrLf & _
           "  3. O servidor Python esta rodando", vbInformation
End Sub

' ============================================================
' PararBridge — para o timer
' ============================================================
Public Sub PararBridge()
    mRodando = False
    On Error Resume Next
    Application.OnTime Now + TimeSerial(0, 0, 1), "VerificarEEnviarRTD", , False
    On Error GoTo 0

    ' Limpar sinal
    With ThisWorkbook.Sheets(1)
        .Cells(1, 1).Value = 0
        .Cells(1, 2).Value = 0
        .Cells(1, 3).Value = 0
        .Cells(1, 4).Value = 0
    End With

    MsgBox "Fluxo Bridge RTD parado.", vbInformation
End Sub

' ============================================================
' InserirFormulasRTD — insere automaticamente as formulas RTD
' ============================================================
Public Sub InserirFormulasRTD()
    Dim sAtivo As String
    Dim sSufixo As String
    Dim ws As Worksheet

    sAtivo = InputBox("Digite o codigo do ativo (ex: PETR4, VALE3, WINFUT):", _
                      "Configurar RTD", ASSET)
    If sAtivo = "" Then Exit Sub

    ' Detectar sufixo: futuros usam _B_0, acoes usam _F_0
    If UCase(sAtivo) Like "WIN*" Or UCase(sAtivo) Like "DOL*" Or _
       UCase(sAtivo) Like "IND*" Or UCase(sAtivo) Like "WDO*" Or _
       UCase(sAtivo) Like "BGI*" Then
        sSufixo = "_B_0"
    Else
        sSufixo = "_F_0"
    End If

    Dim sAtivoRTD As String
    sAtivoRTD = UCase(sAtivo) & sSufixo

    Set ws = ThisWorkbook.Sheets(1)

    ' Inserir formulas RTD
    ws.Cells(1, 5).Formula = "=RTD(""rtdtrading.rtdserver"",,""" & sAtivoRTD & """,""ULT"")"
    ws.Cells(1, 6).Formula = "=RTD(""rtdtrading.rtdserver"",,""" & sAtivoRTD & """,""VOL"")"
    ws.Cells(1, 7).Formula = "=RTD(""rtdtrading.rtdserver"",,""" & sAtivoRTD & """,""ACP"")"
    ws.Cells(1, 8).Formula = "=RTD(""rtdtrading.rtdserver"",,""" & sAtivoRTD & """,""AVD"")"
    ws.Cells(1, 9).Formula = "=RTD(""rtdtrading.rtdserver"",,""" & sAtivoRTD & """,""NEG"")"

    ' Labels na linha 2 para referencia
    ws.Cells(2, 1).Value = "Sinal"
    ws.Cells(2, 2).Value = "Confianca"
    ws.Cells(2, 3).Value = "Preco"
    ws.Cells(2, 4).Value = "Stop"
    ws.Cells(2, 5).Value = "ULT (RTD)"
    ws.Cells(2, 6).Value = "VOL (RTD)"
    ws.Cells(2, 7).Value = "ACP (RTD)"
    ws.Cells(2, 8).Value = "AVD (RTD)"
    ws.Cells(2, 9).Value = "NEG (RTD)"

    MsgBox "Formulas RTD inseridas para " & sAtivoRTD & "!" & vbCrLf & _
           "Verifique se os dados estao chegando nas celulas E1:I1.", vbInformation
End Sub

' ============================================================
' VerificarEEnviarRTD — loop principal (chamado pelo timer)
' ============================================================
Public Sub VerificarEEnviarRTD()
    If Not mRodando Then Exit Sub

    Dim ws As Worksheet
    Set ws = ThisWorkbook.Sheets(1)

    ' -- Ler dados RTD do Profit (celulas E1:I1)
    Dim dLastPrice As Double
    Dim dVolume As Double
    Dim sAgenteCompra As String
    Dim sAgenteVenda As String
    Dim lTradeCount As Long

    On Error Resume Next
    dLastPrice = CDbl(ws.Cells(1, 5).Value)       ' E1 = ULT (ultimo preco)
    dVolume = CDbl(ws.Cells(1, 6).Value)           ' F1 = VOL (volume)
    sAgenteCompra = CStr(ws.Cells(1, 7).Value)    ' G1 = ACP (agente compra)
    sAgenteVenda = CStr(ws.Cells(1, 8).Value)     ' H1 = AVD (agente venda)
    lTradeCount = CLng(ws.Cells(1, 9).Value)       ' I1 = NEG (num negocios)
    On Error GoTo 0

    ' -- Enviar tick ao servidor Python somente se houve novo negocio
    If lTradeCount > mUltimoTradeCount And dLastPrice > 0 Then
        mUltimoTradeCount = lTradeCount

        ' RTD nao tem campo de lado (C/V) direto, mas tem agente compra/venda.
        ' O servidor Python determina o lado pela analise do fluxo.
        ' Enviamos ambos os agentes para o servidor decidir.
        Dim sSide As String
        sSide = "N"   ' N = nao determinado (servidor infere)

        ' Montar JSON do tick
        Dim sTickJSON As String
        sTickJSON = "{""price"":" & Format(dLastPrice, "0.00") & _
                    ",""qty"":" & Format(dVolume, "0") & _
                    ",""broker"":""" & sAgenteCompra & """" & _
                    ",""broker_sell"":""" & sAgenteVenda & """" & _
                    ",""side"":""" & sSide & """}"

        ' Enviar POST /tick
        EnviarPOST PYTHON_URL & "/tick", sTickJSON

        ' -- Consultar sinal atual (GET /signal)
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

            ' Converter sinal texto -> codigo numerico para NTSL
            Dim iSinalNum As Integer
            Select Case UCase(sSinalVal)
                Case "BUY":   iSinalNum = 1
                Case "SELL":  iSinalNum = -1
                Case "CLOSE": iSinalNum = 2
                Case Else:    iSinalNum = 0   ' WAIT
            End Select

            ' Gravar nas celulas de saida (lidas pelo robo NTSL via DDE)
            ws.Cells(1, 1).Value = iSinalNum  ' A1 = iSinalExterno
            ws.Cells(1, 2).Value = dConf      ' B1 = fConfiancaSinal
            ws.Cells(1, 3).Value = dPreco     ' C1 = fPrecoSinal
            ws.Cells(1, 4).Value = dStop      ' D1 = fStopSinal
        End If
    End If

    ' Reagendar proxima execucao
    If mRodando Then
        Application.OnTime Now + TimeSerial(0, 0, 0) + INTERVAL_MS / 86400000#, _
                            "VerificarEEnviarRTD", , True
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
    ' Silencioso: servidor pode nao estar ativo
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
