@echo off
REM Sobe o dashboard e abre o navegador. Feche esta janela (ou Ctrl+C) para parar.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  O ambiente virtual nao existe. Rode uma vez:
    echo.
    echo    py -m venv .venv
    echo    .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "data\database.duckdb" (
    echo.
    echo  A base ainda nao foi criada. Rode uma vez:
    echo.
    echo    .venv\Scripts\python.exe cli.py init
    echo    .venv\Scripts\python.exe cli.py ingest caminho\para\export-mt5.csv
    echo.
    pause
    exit /b 1
)

echo.
echo  Dataframe  -  http://127.0.0.1:8050
echo  Feche esta janela para parar o servidor.
echo.

REM abre o navegador depois que o servidor teve tempo de subir
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start "" http://127.0.0.1:8050"

.venv\Scripts\python.exe ui\app.py
pause
