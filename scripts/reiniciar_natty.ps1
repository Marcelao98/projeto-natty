# Reinicia a Natty rodando pela tarefa agendada "Natty" (aplica codigo novo).
# Uso: botao direito > "Executar com o PowerShell", ou
#      powershell -ExecutionPolicy Bypass -File scripts\reiniciar_natty.ps1 [-Parar]
# Precisa de administrador: a tarefa roda em logon S4U (sessao 0), cujos
# processos um terminal comum nao enxerga. O script pede elevacao sozinho.
param([switch]$Parar)

$eu = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $eu.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $argumentos = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($Parar) { $argumentos += " -Parar" }
    Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList $argumentos
    exit
}

$proj = Split-Path $PSScriptRoot -Parent
$log = Join-Path $proj 'logs\natty.log'

# Parar a tarefa encerra o .bat, mas o python.exe filho sobrevive: mata a arvore.
Stop-ScheduledTask -TaskName Natty
$venvPython = Join-Path $proj '.venv\Scripts\python.exe'
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.ExecutablePath -eq $venvPython } |
    ForEach-Object { taskkill /T /F /PID $_.ProcessId | Out-Null }

if ($Parar) {
    Add-Content $log "[$(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')] Natty parada (reiniciar_natty.ps1 -Parar)" -Encoding UTF8
} else {
    Start-ScheduledTask -TaskName Natty
}
