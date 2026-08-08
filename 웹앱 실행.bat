@echo off
chcp 65001 >nul
rem Start the AI Study Mate web server (PC + phone)
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [!] Python not found on PATH.
    echo     https://www.python.org/downloads/
    echo.
    pause
    exit /b
)

python -c "import flask" >nul 2>nul
if errorlevel 1 (
    echo Installing Flask...
    python -m pip install flask
)

rem The browser is opened by app.py once the server is actually up.
rem The server exits by itself when every browser window is closed,
rem so this window closes with it. Pause only when something went wrong.
python "web\app.py"
if errorlevel 1 pause
