@echo off
chcp 65001 >nul
title Balanca Transtino - Instalar leitor de placas
cd /d "%~dp0"

echo Instalando o leitor de placas (fast-alpr) na pasta lpr_venv...
echo Precisa de internet so nesta instalacao (uns 250 MB).
echo.
if not exist "lpr_venv\Scripts\python.exe" python -m venv lpr_venv
"lpr_venv\Scripts\python.exe" -m pip install --upgrade pip
"lpr_venv\Scripts\python.exe" -m pip install "fast-alpr[onnx]"
echo.
echo Baixando os modelos de leitura de placa...
"lpr_venv\Scripts\python.exe" -c "from fast_alpr import ALPR; ALPR(detector_model='yolo-v9-s-608-license-plate-end2end', ocr_model='cct-s-v2-global-model'); print('Leitor de placas pronto.')"
echo.
echo Pronto. Feche e abra de novo o sistema pelo atalho "Pesagem Transtino".
pause
