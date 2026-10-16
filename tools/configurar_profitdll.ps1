# Grava as credenciais da ProfitDLL como variáveis de ambiente do usuário (HKCU).
# Rode numa janela PowerShell sua — os valores não aparecem na tela nem no histórico.
#   powershell -ExecutionPolicy Bypass -File tools\configurar_profitdll.ps1

function Ler-Segredo($rotulo) {
    $seguro = Read-Host $rotulo -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($seguro)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

$key  = Ler-Segredo "Código de ativação"
$user = Read-Host "Usuário (login Nelogica)"
$pass = Ler-Segredo "Senha"

if (-not $key -or -not $user -or -not $pass) { Write-Host "Algum campo ficou vazio; nada foi gravado."; exit 1 }

[Environment]::SetEnvironmentVariable("PROFITDLL_KEY",  $key,  "User")
[Environment]::SetEnvironmentVariable("PROFITDLL_USER", $user, "User")
[Environment]::SetEnvironmentVariable("PROFITDLL_PASS", $pass, "User")
[Environment]::SetEnvironmentVariable("PROFITDLL_PATH", "C:\ProfitDLL\Win64\ProfitDLL.dll", "User")
[Environment]::SetEnvironmentVariable("PROFITDLL_TYPES_DIR", "C:\ProfitDLL\Exemplo Python", "User")
Write-Host "Credenciais gravadas (PROFITDLL_KEY/USER/PASS/PATH/TYPES_DIR)."
