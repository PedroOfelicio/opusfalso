@echo off
title Instalador do Gadosso Edit
echo Instalador do Gadosso Edit - editor de video com IA
echo.
echo Vai instalar (se faltar) Python, FFmpeg e Node.js e baixar o Gadosso Edit.
echo Na primeira vez leva de 10 a 30 minutos, dependendo da internet.
echo.
pause
rem Usa o instalar.ps1 ao lado deste arquivo; se nao houver, baixa o mais recente do GitHub
set "SCRIPT=%~dp0instalar.ps1"
if not exist "%SCRIPT%" (
  set "SCRIPT=%TEMP%\clipador_instalar.ps1"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest 'https://raw.githubusercontent.com/PedroOfelicio/opusfalso/main/instalador/instalar.ps1' -OutFile '%TEMP%\clipador_instalar.ps1' -UseBasicParsing"
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
echo.
pause
