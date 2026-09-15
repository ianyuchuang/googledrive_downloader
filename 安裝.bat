@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title 施工照片下載工具 － 安裝
cd /d "%~dp0"

echo.
echo ============================================================
echo    施工照片下載工具　安裝
echo ============================================================
echo.

rem ---------- 1. 找 Python ----------
set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY (
    python --version >nul 2>&1 && set PY=python
)

if not defined PY (
    echo [1/4] 這台電腦還沒有 Python。
    echo.
    winget --version >nul 2>&1
    if errorlevel 1 goto NOWINGET
    echo       可以幫你自動安裝，過程約 2 分鐘。
    echo.
    choice /c YN /n /m "      要現在自動安裝 Python 嗎？(Y=好 / N=我自己來) "
    if errorlevel 2 goto NOWINGET
    echo.
    echo       安裝中，請稍候…
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    echo.
    echo ============================================================
    echo    Python 裝好了，但要「關掉這個視窗、重新雙擊 安裝.bat」
    echo    才吃得到新的設定。
    echo ============================================================
    echo.
    pause
    exit /b 0
)

echo [1/4] Python：
%PY% --version
echo.

rem ---------- 2. 安裝套件 ----------
echo [2/4] 安裝需要的套件（PyQt5、requests）…
echo.
%PY% -m pip install --upgrade pip --quiet
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo    ✗ 套件安裝失敗。請確認這台電腦連得上網際網路，
    echo      公司網路若有 Proxy 需先設定好，再重跑一次。
    echo.
    pause
    exit /b 1
)
echo.
echo    ✔ 套件安裝完成
echo.

rem ---------- 3. 設定精靈 ----------
echo [3/4] 進入首次設定…
echo.
%PY% setup_wizard.py

rem ---------- 4. 桌面捷徑 ----------
echo.
echo [4/4] 建立桌面捷徑…
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$w=New-Object -ComObject WScript.Shell; $p=Join-Path $w.SpecialFolders('Desktop') '施工照片下載.lnk'; $s=$w.CreateShortcut($p); $s.TargetPath='%~dp0執行.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%SystemRoot%\system32\imageres.dll,3'; $s.Description='施工照片下載工具'; $s.Save()" >nul 2>&1
if errorlevel 1 (
    echo    （捷徑沒建成，直接用資料夾裡的 執行.bat 也可以）
) else (
    echo    ✔ 桌面上已經有「施工照片下載」捷徑
)

echo.
echo ============================================================
echo    安裝完成！以後雙擊桌面的「施工照片下載」就能用。
echo ============================================================
echo.
pause
exit /b 0

:NOWINGET
echo.
echo       請先自己安裝 Python：
echo         https://www.python.org/downloads/
echo.
echo       ★ 安裝畫面第一頁務必勾選
echo         「Add python.exe to PATH」
echo.
echo       裝完之後，重新雙擊這個 安裝.bat。
echo.
start "" https://www.python.org/downloads/
pause
exit /b 1
