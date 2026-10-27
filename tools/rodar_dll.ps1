# Sobe o Fluxo Server no modo dll lendo as variáveis PROFITDLL_* gravadas no usuário
# (funciona mesmo em terminais abertos antes do configurar_profitdll.ps1).
#   powershell -ExecutionPolicy Bypass -File tools\rodar_dll.ps1 -Asset PETR4 [-Radar] [-Leilao]
param([string]$Asset = "PETR4", [string]$TickSize = "0.01", [string]$Gravar = "", [switch]$Radar, [switch]$Leilao)

foreach ($n in "PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS", "PROFITDLL_PATH", "PROFITDLL_TYPES_DIR") {
    $v = [Environment]::GetEnvironmentVariable($n, "User")
    if (-not $v) { Write-Host "Falta $n — rode tools\configurar_profitdll.ps1"; exit 1 }
    Set-Item "env:$n" $v
}
$env:PYTHONIOENCODING = "utf-8"
$args_ = @("-X", "utf8", "main.py", "--asset", $Asset, "--modo", "dll", "--tick-size", $TickSize)
if ($Gravar) { $args_ += @("--gravar", $Gravar) }
if ($Radar) { $args_ += "--radar" }
if ($Leilao) { $args_ += "--leilao" }
Set-Location (Split-Path $PSScriptRoot -Parent)
python @args_
