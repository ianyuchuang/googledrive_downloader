@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title 資料夾檔案下載工具
cd /d "%~dp0"

rem ============================================================
rem  找 Python
rem    PYW = 沒有主控台的版本（pythonw / pyw），拿來開 GUI
rem    PY  = 一般版本（python / py），拿來跑檢查
rem  用 --version 實際執行一次，才能濾掉 Windows 市集的假 python.exe
rem  後設定的優先，所以 py / pyw 會蓋掉 python / pythonw
rem ============================================================
set "PYW="
set "PY="

pythonw --version >nul 2>&1
if not errorlevel 1 set "PYW=pythonw"
pyw -3 --version >nul 2>&1
if not errorlevel 1 set "PYW=pyw -3"

python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"

if not defined PY if not defined PYW goto NOPY
if not defined PYW set "PYW=%PY%"
if not defined PY set "PY=%PYW%"

rem ============================================================
rem  還沒設定過（沒有 settings.json，或裡面的金鑰是空的）就先安裝
rem ============================================================
if not exist "settings.json" goto SETUP

%PY% -c "import json,sys;sys.exit(0 if json.load(open('settings.json',encoding='utf-8')).get('api_key') else 1)" >nul 2>&1
if errorlevel 1 goto SETUP

rem ============================================================
rem  開程式
rem ============================================================
start "" %PYW% main.py
exit /b 0


:SETUP
echo.
echo   還沒設定 API 金鑰，先跑一次安裝…
echo.
call "%~dp0安裝.bat"
exit /b 0


:NOPY
echo.
echo   找不到 Python，請先雙擊「安裝.bat」。
echo.
pause
exit /b 1
