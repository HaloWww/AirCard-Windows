@echo off
setlocal
title AirCard for Windows
cd /d "%~dp0"

py -3.12 -c "import sys; raise SystemExit(0 if sys.maxsize > 2**32 else 1)" >nul 2>nul
if errorlevel 1 (
    echo ========================================================
    echo AirCard requires 64-bit Python 3.12.
    echo Download it from https://www.python.org/downloads/
    echo During setup, enable the Python launcher option.
    echo ========================================================
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo ========================================================
    echo AirCard for Windows - Initializing Environment...
    echo ========================================================
    py -3.12 -m venv .venv
    if errorlevel 1 goto :setup_failed
    echo Installing required packages...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :setup_failed
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :setup_failed
    echo Setup complete!
    echo ========================================================
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] The existing .venv was created with an unsupported Python version.
    echo Delete the .venv folder and run this launcher again.
    pause
    exit /b 1
)

if "%~1"=="--cli" (
    ".venv\Scripts\python.exe" main.py %*
    if %errorlevel% neq 0 (
        echo.
        echo Program exited with an error.
        pause
    )
    exit /b %errorlevel%
)

start "" ".venv\Scripts\pythonw.exe" app.py
exit /b 0

:setup_failed
echo.
echo [ERROR] AirCard setup failed. Review the message above and try again.
pause
exit /b 1
