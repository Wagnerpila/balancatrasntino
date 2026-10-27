@echo off
chcp 65001 >nul
title Balanca Transtino - Sistema de Pesagem
cd /d "%~dp0"

rem Usa o Python do Venv do projeto antigo se existir; senao, o Python do Windows.
set "PY=%~dp0..\Venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" servidor.py
echo.
echo O servidor foi encerrado.
pause
