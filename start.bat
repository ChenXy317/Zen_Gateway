@echo off
chcp 65001 >nul
title Zen Gateway - OpenCode 本地网关

echo ========================================================
echo   Zen Gateway: OpenCode 免费模型本地三协议网关
echo ========================================================

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未在系统 PATH 中检测到 Python，请先安装 Python 3.9+。
    pause
    exit /b 1
)

python -m app.main
if %errorlevel% neq 0 (
    echo.
    echo [提示] 尝试安装依赖后启动...
    python -m pip install -r requirements.txt
    python -m app.main
)

pause
