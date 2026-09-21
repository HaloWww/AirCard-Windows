@echo off
setlocal
chcp 65001 >nul
title AirCard 卡面助手
cd /d "%~dp0"

py -3.12 -c "import sys; raise SystemExit(0 if sys.maxsize > 2**32 else 1)" >nul 2>nul
if errorlevel 1 (
    echo ========================================================
    echo AirCard 需要 64 位 Python 3.12。
    echo 请从 https://www.python.org/downloads/ 下载。
    echo 安装时请启用 Python Launcher 选项。
    echo ========================================================
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo ========================================================
    echo AirCard - 正在初始化运行环境...
    echo ========================================================
    py -3.12 -m venv .venv
    if errorlevel 1 goto :setup_failed
    echo 正在安装所需组件...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :setup_failed
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :setup_failed
    echo 安装完成！
    echo ========================================================
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [错误] 现有 .venv 使用了不受支持的 Python 版本。
    echo 请删除 .venv 文件夹后重新运行本启动器。
    pause
    exit /b 1
)

if "%~1"=="--cli" (
    ".venv\Scripts\python.exe" main.py %*
    if %errorlevel% neq 0 (
        echo.
        echo 程序异常退出。
        pause
    )
    exit /b %errorlevel%
)

start "" ".venv\Scripts\pythonw.exe" app.py
exit /b 0

:setup_failed
echo.
echo [错误] AirCard 安装失败。请检查上方信息后重试。
pause
exit /b 1
