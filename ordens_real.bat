@echo off
REM Processo das ordens da conta real: le os desejados da captura e envia so na conta real.
REM Aberto pelo iniciar.bat. Se cair, reabre sozinho com espera crescente.
cd /d "%~dp0"
title Dataframe - Ordens real
set ESPERA=10
:laco
.venv\Scripts\python.exe ordens_real.py
set CODIGO=%ERRORLEVEL%
if "%CODIGO%"=="0" exit /b 0
REM 4 = ja ha um processo das ordens reais aberto (iniciar.bat reaberto): sai sem incomodar
if "%CODIGO%"=="4" exit /b 0
if "%CODIGO%"=="3" (
    echo.
    echo  As ordens reais pararam e nao vao reabrir sozinhas: falta configuracao.
    echo  Cadastre a conta real com o caminho do terminal. Detalhes em data\ao_vivo\ordens_real.log
    echo.
    pause
    exit /b 3
)
echo  As ordens reais cairam (codigo %CODIGO%). Reabrindo em %ESPERA% s...
timeout /t %ESPERA% /nobreak >nul
if %ESPERA%==10 (set ESPERA=30) else if %ESPERA%==30 (set ESPERA=60) else if %ESPERA%==60 (set ESPERA=120) else (set ESPERA=300)
goto laco
