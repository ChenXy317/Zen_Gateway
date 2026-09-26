@echo off
title Zen Gateway
chcp 65001 >nul

echo ========================================================
echo   Zen Gateway: OpenCode Free Tier Local Gateway
echo ========================================================

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found in PATH. Please install Python 3.9+.
    pause
    exit /b 1
)

python -m app.main %*
if %errorlevel% neq 0 (
    echo.
    echo [INFO] Installing dependencies and retrying...
    python -m pip install -r requirements.txt
    python -m app.main %*
)

pause
