# Instalador / atualizador do Clipador (Windows 10/11).
#   Instalar:   powershell -ExecutionPolicy Bypass -File instalar.ps1
#   Atualizar:  powershell -ExecutionPolicy Bypass -File instalar.ps1 -Atualizar
# Instala (se faltar) Python 3.12, FFmpeg e Node.js pelo winget, baixa o app do GitHub, prepara o ambiente
# (sem as bibliotecas da NVIDIA se o PC nao tiver placa NVIDIA), monta a interface, cria o atalho e abre o app.
# Tudo fica em %LOCALAPPDATA%\Clipador (app, ambiente Python e dados), fora do OneDrive.
param(
    [switch]$Atualizar,
    [switch]$NaoAbrir,
    [string]$NomeAtalho = "Clipador",
    [string]$Destino = (Join-Path $env:LOCALAPPDATA "Clipador"),
    [string]$Repo = "PedroOfelicio/opusfalso",
    [string]$Ramo = "main"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest fica muito mais rapido
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Passo($texto) { Write-Host "`n==> $texto" -ForegroundColor Cyan }
function Ok($texto) { Write-Host "    $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "    $texto" -ForegroundColor Yellow }
function Falhar($texto) {
    Write-Host "`nERRO: $texto" -ForegroundColor Red
    Write-Host "Se nao conseguir resolver, mande um print desta janela para quem te passou o Clipador."
    Read-Host "Aperte Enter para fechar"
    exit 1
}
function RecarregarPath {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Tem($comando) { [bool](Get-Command $comando -ErrorAction SilentlyContinue) }
function InstalarWinget($id, $nome) {
    if (-not (Tem "winget")) {
        Falhar "O winget (Instalador de Aplicativos da Microsoft) nao esta disponivel. Atualize o 'App Installer' pela Microsoft Store e rode de novo."
    }
    Aviso "Instalando $nome (pode pedir permissao do Windows)..."
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements | Out-Host
    RecarregarPath
}

$app = Join-Path $Destino "app"
$venv = Join-Path $Destino "venv"
$dados = Join-Path $Destino "dados"
Write-Host "Clipador - editor de video com IA" -ForegroundColor Magenta
Write-Host ("Instalando em " + $Destino)

# ------------------------------------------------------------------ espaco e programas
Passo "Conferindo o espaco em disco"
$disco = Get-PSDrive -Name ($Destino.Substring(0, 1))
$livreGB = [math]::Round($disco.Free / 1GB, 1)
if (-not $Atualizar -and $livreGB -lt 10) { Falhar "Pouco espaco: $livreGB GB livres. O Clipador precisa de uns 10 GB." }
Ok "$livreGB GB livres"

Passo "Conferindo Python 3.12, FFmpeg e Node.js"
RecarregarPath
$python = $null
$candidatos = @((Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"), "C:\Program Files\Python312\python.exe")
foreach ($c in $candidatos) { if (Test-Path $c) { $python = $c; break } }
if (-not $python -and (Tem "py")) {
    try { $python = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null) } catch { $python = $null }
}
if (-not $python) {
    InstalarWinget "Python.Python.3.12" "Python 3.12"
    foreach ($c in $candidatos) { if (Test-Path $c) { $python = $c; break } }
    if (-not $python) { Falhar "O Python 3.12 nao foi encontrado depois de instalar. Reinicie o PC e rode o instalador de novo." }
}
Ok "Python: $python"
if (-not (Tem "ffmpeg")) { InstalarWinget "Gyan.FFmpeg" "FFmpeg" }
if (-not (Tem "ffmpeg")) { Falhar "O FFmpeg nao foi encontrado depois de instalar. Reinicie o PC e rode o instalador de novo." }
Ok "FFmpeg ok"
if (-not (Tem "npm")) { InstalarWinget "OpenJS.NodeJS.LTS" "Node.js" }
if (-not (Tem "npm")) { Falhar "O Node.js nao foi encontrado depois de instalar. Reinicie o PC e rode o instalador de novo." }
Ok "Node.js ok"

# ------------------------------------------------------------------ app (do GitHub)
Passo "Baixando o Clipador do GitHub ($Repo, $Ramo)"
New-Item -ItemType Directory -Force $Destino | Out-Null
$sha = "desconhecida"
try { $sha = (Invoke-RestMethod "https://api.github.com/repos/$Repo/commits/$Ramo" -Headers @{ "User-Agent" = "Clipador" }).sha } catch { Aviso "Nao consegui ler a versao no GitHub (segue assim mesmo)." }
$zip = Join-Path $env:TEMP "clipador_$([guid]::NewGuid().ToString('N')).zip"
$tmp = Join-Path $env:TEMP "clipador_$([guid]::NewGuid().ToString('N'))"
try {
    Invoke-WebRequest "https://codeload.github.com/$Repo/zip/refs/heads/$Ramo" -OutFile $zip -UseBasicParsing
} catch { Falhar "Nao consegui baixar o app do GitHub: $($_.Exception.Message)" }
Expand-Archive $zip -DestinationPath $tmp -Force
$novo = Get-ChildItem $tmp -Directory | Select-Object -First 1
# reaproveita as dependencias do Node da versao anterior (atualizar fica bem mais rapido)
foreach ($pasta in @("frontend\node_modules", "remotion\node_modules")) {
    $velha = Join-Path $app $pasta
    if (Test-Path $velha) { Move-Item $velha (Join-Path $novo.FullName $pasta) -Force }
}
if (Test-Path $app) { Remove-Item $app -Recurse -Force }
Move-Item $novo.FullName $app
Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
@{ repo = $Repo; ramo = $Ramo; sha = $sha; instalado_em = (Get-Date).ToString("s") } | ConvertTo-Json | Set-Content (Join-Path $app "versao.txt") -Encoding ASCII
Ok "Versao $($sha.Substring(0, [math]::Min(7, $sha.Length)))"

# ------------------------------------------------------------------ ambiente Python
Passo "Preparando o ambiente Python (na primeira vez demora: baixa ~1 a 3 GB)"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) { & $python -m venv $venv }
$pyVenv = Join-Path $venv "Scripts\python.exe"
$temNvidia = [bool](Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match "NVIDIA" })
$req = Get-Content (Join-Path $app "backend\requirements.txt")
if (-not $temNvidia) {
    $req = $req | Where-Object { $_ -notmatch "^nvidia-" }
    Aviso "Sem placa NVIDIA: a transcricao vai usar o processador (funciona, mas e mais lenta)."
} else { Ok "Placa NVIDIA encontrada: a transcricao vai usar a GPU." }
$reqTmp = Join-Path $env:TEMP "clipador_requirements.txt"
$req | Set-Content $reqTmp -Encoding ASCII
& $pyVenv -m pip install --upgrade pip --quiet --disable-pip-version-check
& $pyVenv -m pip install -r $reqTmp --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Falhar "A instalacao das bibliotecas Python falhou (veja as mensagens acima)." }
Ok "Bibliotecas Python ok"

# ------------------------------------------------------------------ interface e legenda animada
Passo "Montando a interface e a legenda animada"
Push-Location (Join-Path $app "frontend")
npm install --no-audit --no-fund --loglevel=error | Out-Host
npm run build | Out-Host
$okInterface = Test-Path "dist\index.html"
Pop-Location
if (-not $okInterface) { Falhar "A interface nao foi montada (npm run build)." }
Push-Location (Join-Path $app "remotion")
npm install --no-audit --no-fund --loglevel=error | Out-Host
Pop-Location
Ok "Interface ok"

# ------------------------------------------------------------------ pastas, atalho e abertura
Passo "Criando o atalho"
# Sem variaveis de ambiente: o app acha a pasta de dados ao lado dele (<Destino>\dados)
New-Item -ItemType Directory -Force $dados | Out-Null
& (Join-Path $app "app\criar_atalho.ps1") -Venv $venv -Nome $NomeAtalho | Out-Host

Write-Host "`nPronto! O Clipador esta instalado." -ForegroundColor Green
Write-Host "Abra pelo atalho 'Clipador' na area de trabalho. Na primeira vez ele pede a sua chave do Claude."
if (-not $NaoAbrir) {
    Start-Process -FilePath (Join-Path $venv "Scripts\pythonw.exe") -ArgumentList "`"$(Join-Path $app 'app\clipador.pyw')`"" -WorkingDirectory (Join-Path $app "app")
}
Start-Sleep -Seconds 3
