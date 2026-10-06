@echo off
rem Atualiza a tabela jogadores com TODOS os membros do servidor (sem bots).
rem Duplo clique, ou: scripts\sincronizar_membros.bat
rem A Natty ja faz isso sozinha ao subir e a cada 24h; isto e pra rodar na mao.
setlocal
cd /d "%~dp0.."
set PYTHONUTF8=1
set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"
"%PYTHON%" scripts\sincronizar_membros.py
pause
