@echo off
REM Inicia o servidor local e abre a interface no navegador.
REM (usa a interface compilada em frontend\dist; para desenvolver, veja o README)
set VENV=C:\opusfalso-dados\venv
cd /d "%~dp0backend"
start "" http://127.0.0.1:8000
"%VENV%\Scripts\python.exe" -m uvicorn api:app --host 127.0.0.1 --port 8000 --no-access-log
pause
