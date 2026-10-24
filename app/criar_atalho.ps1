# Cria os atalhos na area de trabalho e no menu Iniciar (abre o app com janela propria).
# Uso: powershell -ExecutionPolicy Bypass -File app\criar_atalho.ps1 [-Venv <pasta do venv>] [-Nome "Gadosso Edit"]
param([string]$Venv = "", [string]$Nome = "Gadosso Edit")
$venv = if ($Venv) { $Venv } elseif ($env:OPUSFALSO_VENV) { $env:OPUSFALSO_VENV } else { "C:\opusfalso-dados\venv" }
$pythonw = Join-Path $venv "Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { Write-Error "Nao achei $pythonw. Rode o instalador antes."; exit 1 }
$lancador = Join-Path $PSScriptRoot "clipador.pyw"
$icone = Join-Path $PSScriptRoot "icone.ico"
$shell = New-Object -ComObject WScript.Shell
$destinos = @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("Programs")) ""))
foreach ($pasta in $destinos) {
    $arquivo = Join-Path $pasta "$Nome.lnk"
    $atalho = $shell.CreateShortcut($arquivo)
    $atalho.TargetPath = $pythonw
    $atalho.Arguments = "`"$lancador`""
    $atalho.WorkingDirectory = $PSScriptRoot
    $atalho.IconLocation = "$icone,0"
    $atalho.Description = "Gadosso Edit - editor de video com IA"
    $atalho.Save()
    Write-Output "Atalho criado: $arquivo"
}
