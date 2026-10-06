@echo off
setlocal

rem Supervisor da Natty: roda bot.py em loop e reinicia se o processo cair.
rem Pensado para ser chamado pelo Agendador de Tarefas do Windows.

rem Vai para a raiz do projeto (pasta acima de scripts\), independente de onde
rem o .bat foi chamado -- garante que credentials.json e .env sejam achados.
cd /d "%~dp0.."

if not exist logs mkdir logs
set "LOG=logs\natty.log"

rem Saida do Python sem buffer (log aparece na hora) e em UTF-8 (evita crash
rem ao escrever acentos/emoji num arquivo redirecionado).
set PYTHONUNBUFFERED=1
set PYTHONUTF8=1

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

:loop
echo [%date% %time%] Iniciando Natty com %PYTHON% >> "%LOG%"
"%PYTHON%" bot.py >> "%LOG%" 2>&1
set "CODIGO=%errorlevel%"
rem Codigo 3 = banco (data\natty.db) ilegivel. Reiniciar nao conserta: para o
rem loop e espera alguem rodar scripts\restaurar_banco.py.
if "%CODIGO%"=="3" goto banco_ilegivel
echo [%date% %time%] Natty encerrou (codigo %CODIGO%). Reiniciando em 10s... >> "%LOG%"
rem ping em vez de timeout: timeout falha sem console (Agendador de Tarefas).
ping -n 11 127.0.0.1 > nul
goto loop

:banco_ilegivel
echo [%date% %time%] Banco ilegivel: Natty PARADA, sem reiniciar. Rode python scripts\restaurar_banco.py e depois reinicie a tarefa. >> "%LOG%"
exit /b 3
