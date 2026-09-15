@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title 施工照片下載工具 － 連線診斷
cd /d "%~dp0"

set "PY="
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"

if not defined PY (
    echo 找不到 Python，請先雙擊「安裝.bat」。
    pause
    exit /b 1
)

%PY% 診斷.py
echo.
pause
