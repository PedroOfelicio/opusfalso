# Cria os atalhos "Clipador" na area de trabalho e no menu Iniciar (abre o app com janela propria).
# Uso: powershell -ExecutionPolicy Bypass -File app\criar_atalho.ps1
$venv = if ($env:OPUSFALSO_VENV) { $env:OPUSFALSO_VENV } else { "C:\opusfalso-dados\venv" }
$pythonw = Join-Path $venv "Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { Write-Error "Nao achei $pythonw. Rode o instalador antes."; exit 1 }
$lancador = Join-Path $PSScriptRoot "clipador.pyw"
$icone = Join-Path $PSScriptRoot "icone.ico"
$shell = New-Object -ComObject WScript.Shell
$destinos = @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("Programs")) ""))
foreach ($pasta in $destinos) {
    $atalho = $shell.CreateShortcut((Join-Path $pasta "Clipador.lnk"))
    $atalho.TargetPath = $pythonw
    $atalho.Arguments = "`"$lancador`""
    $atalho.WorkingDirectory = $PSScriptRoot
    $atalho.IconLocation = "$icone,0"
    $atalho.Description = "Clipador - editor de video com IA"
    $atalho.Save()
    Write-Output "Atalho criado: $(Join-Path $pasta 'Clipador.lnk')"
}
