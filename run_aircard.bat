@echo off
title AirCard for Windows
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ========================================================
    echo AirCard for Windows - Initializing Environment...
    echo ========================================================
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        py -3 -m venv .venv
    ) else (
        where python >nul 2>nul
        if %errorlevel% equ 0 (
            python -m venv .venv
        ) else (
            echo [ERROR] Python 3.10+ was not found on your system!
            echo Please install Python from https://www.python.org/
            pause
            exit /b 1
        )
    )
    echo Installing required packages...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    echo Setup complete!
    echo ========================================================
)

".venv\Scripts\python.exe" main.py
if %errorlevel% neq 0 (
    echo.
    echo Program exited with an error.
    pause
)
