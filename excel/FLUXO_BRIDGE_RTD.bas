Attribute VB_Name = "FLUXO_BRIDGE_RTD"
' ============================================================
' FLUXO BRIDGE RTD — Macro VBA para Excel (usa RTD do Profit)
' ============================================================
' Intermediario entre o Profit Pro (RTD) e o servidor Python.
'
' O RTD NAO entrega o Times & Trades, apenas um retrato do ativo
' (ultimo preco, volume e numero de negocios acumulados no dia,
' agentes do ultimo negocio). A macro envia esse retrato BRUTO para
' POST /rtd e o servidor Python infere o negocio:
'   - quantidade = diferenca do volume acumulado
'   - lado agressor = regra da cotacao (bid/ask, se configurados)
'                     ou regra do tick (subiu = compra, caiu = venda)
'
' ARQUITETURA:
'   Profit RTD  ->  Celulas E1:K1 (formulas RTD)
'   Excel       ->  a cada atualizacao do RTD, envia POST /rtd
'   Servidor    ->  Retorna sinal (A1), confianca (B1), preco (C1), stop (D1)
'   NTSL Robot  ->  Le A1:D1 via parametros DDE linkados ao Excel
'
' CELULAS DO EXCEL:
'   A1 = iSinalExterno    (1=BUY, -1=SELL, 0=WAIT, 2=CLOSE)
'   B1 = fConfiancaSinal  (0.0 a 1.0)
'   C1 = fPrecoSinal      (preco do sinal)
'   D1 = fStopSinal       (stop do sinal)
'   E1 = ULT  (ultimo preco)
'   F1 = VOL  (QUANTIDADE acumulada no dia — nao pode ser volume financeiro)
'   G1 = ACP  (agente comprador do ultimo negocio)
'   H1 = AVD  (agente vendedor do ultimo negocio)
'   I1 = NEG  (numero de negocios acumulado)
'   J1 = melhor bid   (opcional — configure CAMPO_BID)
'   K1 = melhor ask   (opcional — configure CAMPO_ASK)
'
' SETUP:
'   1. Importe este modulo (Alt+F11 > Arquivo > Importar)
'   2. No Profit: Ferramentas > Exportar em Tempo Real > RTD
'   3. Rode InserirFormulasRTD() e confira se E1:I1 mostram valores
'      (se aparecer #N/D, troque SUFIXO_ACOES / SUFIXO_FUTUROS)
'   4. RECOMENDADO — envio a cada atualizacao do RTD: clique duas vezes
'      na Planilha1 no editor VBA e cole:
'          Private Sub Worksheet_Calculate()
'              FLUXO_BRIDGE_RTD.AoAtualizarRTD
'          End Sub
'      Sem isso, a macro consulta a cada 1 segundo (perde mais negocios).
'   5. Rode IniciarBridge()
'   6. Linke os parametros do robo NTSL as celulas A1:D1 via DDE Excel
' ============================================================

Option Explicit

' -- Configuracoes
Private Const PYTHON_URL As String = "http://127.0.0.1:5000"
Private Const ASSET As String = "PETR4"

' Sufixo do ativo nas formulas RTD. Se as celulas mostrarem #N/D,
' inverta os dois valores.
Private Const SUFIXO_ACOES As String = "_F_0"
Private Const SUFIXO_FUTUROS As String = "_B_0"

' Campos RTD do melhor bid/ask. Deixe "" se o seu Profit nao tiver.
' Consulte a lista de campos em Exportar em Tempo Real > RTD.
Private Const CAMPO_BID As String = ""
Private Const CAMPO_ASK As String = ""

' -- Estado interno
Private mRodando As Boolean
Private mProcessando As Boolean
Private mUltimoVolume As Double
Private mUltimoNeg As Double
Private mUltimoBid As Double
Private mUltimoAsk As Double

' ============================================================
' IniciarBridge — liga o envio
' ============================================================
Public Sub IniciarBridge()
    If mRodando Then
        MsgBox "Bridge ja esta rodando.", vbInformation
        Exit Sub
    End If

    ' Padrao do Excel e' agrupar atualizacoes RTD a cada 2s — perde negocios
    Application.RTD.ThrottleInterval = 0

    mUltimoVolume = -1
    mUltimoNeg = -1
    mUltimoBid = -1
    mUltimoAsk = -1
    mRodando = True

    With ThisWorkbook.Sheets(1)
        .Cells(1, 1).Value = 0   ' iSinalExterno = WAIT
        .Cells(1, 2).Value = 0   ' fConfiancaSinal
        .Cells(1, 3).Value = 0   ' fPrecoSinal
        .Cells(1, 4).Value = 0   ' fStopSinal
    End With

    ' Timer de seguranca (1s) — complementa o evento Worksheet_Calculate
    Application.OnTime Now + TimeSerial(0, 0, 1), "TimerRTD"

    MsgBox "Fluxo Bridge RTD iniciado!" & vbCrLf & _
           "Servidor Python: " & PYTHON_URL & vbCrLf & vbCrLf & _
           "Certifique-se de que:" & vbCrLf & _
           "  1. As formulas RTD estao em E1:I1" & vbCrLf & _
           "  2. O Profit Pro esta aberto com RTD habilitado" & vbCrLf & _
           "  3. O servidor Python esta rodando (--modo rtd)", vbInformation
End Sub

' ============================================================
' PararBridge — desliga o envio
' ============================================================
Public Sub PararBridge()
    mRodando = False
    On Error Resume Next
    Application.OnTime Now + TimeSerial(0, 0, 1), "TimerRTD", , False
    On Error GoTo 0

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

    If UCase(sAtivo) Like "WIN*" Or UCase(sAtivo) Like "DOL*" Or _
       UCase(sAtivo) Like "IND*" Or UCase(sAtivo) Like "WDO*" Or _
       UCase(sAtivo) Like "BGI*" Then
        sSufixo = SUFIXO_FUTUROS
    Else
        sSufixo = SUFIXO_ACOES
    End If

    Dim sAtivoRTD As String
    sAtivoRTD = UCase(sAtivo) & sSufixo

    Set ws = ThisWorkbook.Sheets(1)

    ws.Cells(1, 5).Formula = FormulaRTD(sAtivoRTD, "ULT")
    ws.Cells(1, 6).Formula = FormulaRTD(sAtivoRTD, "VOL")
    ws.Cells(1, 7).Formula = FormulaRTD(sAtivoRTD, "ACP")
    ws.Cells(1, 8).Formula = FormulaRTD(sAtivoRTD, "AVD")
    ws.Cells(1, 9).Formula = FormulaRTD(sAtivoRTD, "NEG")
    If CAMPO_BID <> "" Then ws.Cells(1, 10).Formula = FormulaRTD(sAtivoRTD, CAMPO_BID)
    If CAMPO_ASK <> "" Then ws.Cells(1, 11).Formula = FormulaRTD(sAtivoRTD, CAMPO_ASK)

    ws.Cells(2, 1).Value = "Sinal"
    ws.Cells(2, 2).Value = "Confianca"
    ws.Cells(2, 3).Value = "Preco"
    ws.Cells(2, 4).Value = "Stop"
    ws.Cells(2, 5).Value = "ULT (RTD)"
    ws.Cells(2, 6).Value = "VOL (RTD)"
    ws.Cells(2, 7).Value = "ACP (RTD)"
    ws.Cells(2, 8).Value = "AVD (RTD)"
    ws.Cells(2, 9).Value = "NEG (RTD)"
    ws.Cells(2, 10).Value = "BID (RTD)"
    ws.Cells(2, 11).Value = "ASK (RTD)"

    MsgBox "Formulas RTD inseridas para " & sAtivoRTD & "!" & vbCrLf & _
           "Verifique se os dados estao chegando nas celulas E1:I1." & vbCrLf & _
           "Se aparecer #N/D, inverta SUFIXO_ACOES e SUFIXO_FUTUROS.", vbInformation
End Sub

Private Function FormulaRTD(sAtivoRTD As String, sCampo As String) As String
    FormulaRTD = "=RTD(""rtdtrading.rtdserver"",,""" & sAtivoRTD & """,""" & sCampo & """)"
End Function

' ============================================================
' TimerRTD — consulta de seguranca a cada 1 segundo
' ============================================================
Public Sub TimerRTD()
    If Not mRodando Then Exit Sub
    AoAtualizarRTD
    Application.OnTime Now + TimeSerial(0, 0, 1), "TimerRTD"
End Sub

' ============================================================
' AoAtualizarRTD — chamado pelo Worksheet_Calculate e pelo timer
' ============================================================
Public Sub AoAtualizarRTD()
    If Not mRodando Or mProcessando Then Exit Sub
    mProcessando = True
    On Error GoTo Fim

    Dim ws As Worksheet
    Set ws = ThisWorkbook.Sheets(1)

    Dim dPreco As Double, dVolume As Double, dNeg As Double
    Dim dBid As Double, dAsk As Double
    dPreco = NumeroCelula(ws.Cells(1, 5))
    dVolume = NumeroCelula(ws.Cells(1, 6))
    dNeg = NumeroCelula(ws.Cells(1, 9))
    dBid = NumeroCelula(ws.Cells(1, 10))
    dAsk = NumeroCelula(ws.Cells(1, 11))

    ' Enviar so' quando algo mudou (novo negocio ou novo bid/ask)
    If dPreco > 0 And (dVolume <> mUltimoVolume Or dNeg <> mUltimoNeg Or _
                       dBid <> mUltimoBid Or dAsk <> mUltimoAsk) Then
        mUltimoVolume = dVolume
        mUltimoNeg = dNeg
        mUltimoBid = dBid
        mUltimoAsk = dAsk

        Dim sJSON As String
        sJSON = "{""price"":" & NumJSON(dPreco) & _
                ",""volume"":" & NumJSON(dVolume) & _
                ",""trades"":" & NumJSON(dNeg) & _
                ",""buyer"":""" & TextoJSON(ws.Cells(1, 7).Text) & """" & _
                ",""seller"":""" & TextoJSON(ws.Cells(1, 8).Text) & """" & _
                ",""bid"":" & NumJSON(dBid) & _
                ",""ask"":" & NumJSON(dAsk) & "}"

        Dim sResp As String
        sResp = EnviarPOST(PYTHON_URL & "/rtd", sJSON)
        If sResp <> "" Then GravarSinal ws, sResp
    End If

Fim:
    mProcessando = False
End Sub

' ============================================================
' GravarSinal — escreve A1:D1 a partir da resposta do servidor
' ============================================================
Private Sub GravarSinal(ws As Worksheet, sResp As String)
    Dim iSinalNum As Integer
    Select Case UCase(ExtrairStr(sResp, """signal"": """, """"))
        Case "BUY":   iSinalNum = 1
        Case "SELL":  iSinalNum = -1
        Case "CLOSE": iSinalNum = 2
        Case Else:    iSinalNum = 0   ' WAIT
    End Select

    ' Val() sempre usa ponto decimal — CDbl() quebraria no Excel em portugues
    ws.Cells(1, 1).Value = iSinalNum
    ws.Cells(1, 2).Value = Val(ExtrairStr(sResp, """confidence"": ", ","))
    ws.Cells(1, 3).Value = Val(ExtrairStr(sResp, """price"": ", ","))
    ws.Cells(1, 4).Value = Val(ExtrairStr(sResp, """stop_price"": ", ","))
End Sub

' ============================================================
' Utilitarios
' ============================================================
Private Function NumeroCelula(c As Range) As Double
    If IsError(c.Value) Then Exit Function
    If IsNumeric(c.Value) Then NumeroCelula = CDbl(c.Value)
End Function

' Numero com ponto decimal, independente do idioma do Windows
Private Function NumJSON(d As Double) As String
    NumJSON = Trim(Str(d))
End Function

Private Function TextoJSON(s As String) As String
    s = Replace(s, "\", "")
    TextoJSON = Replace(s, """", "")
End Function

Private Function EnviarPOST(sURL As String, sBody As String) As String
    On Error GoTo ErrHandler
    Dim oHTTP As Object
    Set oHTTP = CreateObject("WinHttp.WinHttpRequest.5.1")
    oHTTP.Open "POST", sURL, False
    oHTTP.SetRequestHeader "Content-Type", "application/json"
    oHTTP.Send sBody
    If oHTTP.Status = 200 Then EnviarPOST = oHTTP.ResponseText
    Exit Function
ErrHandler:
    EnviarPOST = ""   ' servidor pode nao estar ativo
End Function

Private Function ExtrairStr(sJSON As String, sIni As String, sFim As String) As String
    Dim iPosIni As Long, iPosFim As Long
    iPosIni = InStr(sJSON, sIni)
    If iPosIni = 0 Then Exit Function
    iPosIni = iPosIni + Len(sIni)
    iPosFim = InStr(iPosIni, sJSON, sFim)
    If iPosFim = 0 Then Exit Function
    ExtrairStr = Mid(sJSON, iPosIni, iPosFim - iPosIni)
End Function
