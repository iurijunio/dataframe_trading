@echo off
REM Servico de captura: grava cada candle M1 fechado do WIN$N.
REM Aberto pelo iniciar.bat. Se cair, reabre sozinho com espera crescente.
cd /d "%~dp0"
title Dataframe - Captura
set ESPERA=10
:laco
.venv\Scripts\python.exe captura.py
set CODIGO=%ERRORLEVEL%
if "%CODIGO%"=="0" exit /b 0
REM 4 = ja ha uma captura aberta (iniciar.bat reaberto): sai sem incomodar
if "%CODIGO%"=="4" exit /b 0
if "%CODIGO%"=="3" (
    echo.
    echo  A captura parou e nao vai reabrir sozinha: falta configuracao.
    echo  Detalhes em data\ao_vivo\captura.log
    echo.
    pause
    exit /b 3
)
echo  A captura caiu (codigo %CODIGO%). Reabrindo em %ESPERA% s...
timeout /t %ESPERA% /nobreak >nul
if %ESPERA%==10 (set ESPERA=30) else if %ESPERA%==30 (set ESPERA=60) else if %ESPERA%==60 (set ESPERA=120) else (set ESPERA=300)
goto laco
