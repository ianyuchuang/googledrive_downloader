# -*- coding: utf-8 -*-
"""首次設定精靈（文字介面，由 安裝.bat 呼叫，也可單獨執行）。

做三件事：
1. 帶著使用者去 Google Cloud 申請 API 金鑰（自動開好瀏覽器頁面）
2. 當場驗證金鑰能不能真的讀到照片資料夾
3. 把金鑰與儲存位置寫進 settings.json

如果程式資料夾裡放了 `預設金鑰.txt`，就直接用裡面那把金鑰，不再問使用者。
（發給同事前把自己的金鑰存成這個檔，同事就完全不用申請。）
"""
import os
import sys
import time
import webbrowser

import config
from drive_client import DriveClient, DriveError, parse_folder_id

APP_DIR = config.APP_DIR
PRESET_KEY_FILE = os.path.join(APP_DIR, "預設金鑰.txt")

CONSOLE_URL = "https://console.cloud.google.com/projectcreate"
ENABLE_URL = "https://console.cloud.google.com/apis/library/drive.googleapis.com"
CRED_URL = "https://console.cloud.google.com/apis/credentials"

LINE = "─" * 60


def title(text):
    print("\n" + LINE)
    print("  " + text)
    print(LINE)


def ask(prompt, default=""):
    try:
        s = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    return s or default


def yes(prompt, default=True):
    hint = "(Y/n)" if default else "(y/N)"
    s = ask("%s %s " % (prompt, hint)).lower()
    if not s:
        return default
    return s.startswith("y")


def read_preset_key():
    """讀 預設金鑰.txt；沒有就回空字串。"""
    try:
        with open(PRESET_KEY_FILE, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except (IOError, OSError):
        pass
    return ""


def open_page(url, label):
    print("  正在開啟：%s" % label)
    try:
        webbrowser.open(url)
    except Exception:
        print("  （開不起來的話請自己複製這個網址）")
    print("  %s" % url)
    time.sleep(1)


def guide_apply_key():
    """一步一步帶著申請金鑰。"""
    title("步驟 1／3　申請 Google API 金鑰")
    print("""
這個工具要讀雲端硬碟上的照片，需要一把「API 金鑰」。
只要申請一次，之後就不用再弄。整個過程大約 3 分鐘，免費。

接下來會幫你依序開三個網頁，請照著做：
""")
    ask("  準備好了就按 Enter 開始…")

    print("\n【1-1】建立一個專案")
    open_page(CONSOLE_URL, "建立專案頁")
    print("""
    · 用你的 Google 帳號登入
    · 專案名稱隨便打，例如 photo-downloader
    · 按「建立」，等右上角轉圈結束
""")
    ask("  建好了按 Enter 繼續…")

    print("\n【1-2】啟用 Google Drive API")
    open_page(ENABLE_URL, "Google Drive API 頁")
    print("""
    · 確認左上角的專案是剛剛建的那一個
    · 按藍色的「啟用」按鈕
""")
    ask("  啟用完按 Enter 繼續…")

    print("\n【1-3】建立金鑰")
    open_page(CRED_URL, "憑證頁")
    print("""
    · 上方「+ 建立憑證」→ 選「API 金鑰」
    · 跳出一串 AIza... 開頭的字，按「複製」

    ★ 重要：按下面的「編輯 API 金鑰」，把
        「應用程式限制」設為【無】
      （設成「HTTP 參照網址」會把這支程式擋掉）
      「API 限制」可以選「限制金鑰」→ 只勾 Google Drive API
""")


def verify(key, folder_id):
    """驗證金鑰；成功回傳日期資料夾數量，失敗回傳 None。"""
    print("\n  驗證中…", end="")
    sys.stdout.flush()
    try:
        n = DriveClient(key, folder_id).check()
    except DriveError as e:
        print("\r  ✗ 驗證失敗：%s" % e)
        return None
    except Exception as e:
        print("\r  ✗ 驗證失敗：%s：%s" % (e.__class__.__name__, e))
        return None
    print("\r  ✔ 金鑰可用，讀到 %d 個日期資料夾。   " % n)
    return n


def main():
    cfg = config.load()
    folder_id = cfg.get("folder_id") or config.DEFAULT_FOLDER_ID

    title("施工照片下載工具　首次設定")

    # --- 照片資料夾 ---
    while not folder_id:
        entered = ask("\n  請貼上照片上傳資料夾的雲端硬碟連結（或資料夾 ID）：\n  > ")
        folder_id = parse_folder_id(entered)
        if not folder_id:
            print("  沒有讀到資料夾 ID，請再貼一次。")

    # --- 金鑰 ---
    key = ""
    preset = read_preset_key()
    if preset:
        print("\n  找到「預設金鑰.txt」，直接使用裡面的金鑰。")
        if verify(preset, folder_id) is not None:
            key = preset
        else:
            print("  預設金鑰不能用，改用手動申請。")

    if not key and cfg.get("api_key"):
        print("\n  偵測到之前已經設定過金鑰。")
        if verify(cfg["api_key"], folder_id) is not None:
            if not yes("  要換一把新的嗎？", default=False):
                key = cfg["api_key"]

    if not key:
        guide_apply_key()
        title("步驟 2／3　貼上金鑰")
        while True:
            entered = ask("\n  請貼上金鑰（AIza… 開頭），直接按 Enter 可略過：\n  > ")
            if not entered:
                print("\n  略過金鑰設定。之後可以在程式視窗裡直接填，或重跑 安裝.bat。")
                break
            if verify(entered, folder_id) is not None:
                key = entered
                break
            print("""
  再試一次。常見原因：
    · 金鑰沒複製完整（前後有空白）
    · Google Drive API 還沒啟用，或剛啟用還沒生效（等 1~2 分鐘）
    · 金鑰的「應用程式限制」不是「無」
""")
            if not yes("  要再貼一次嗎？"):
                break

    # --- 儲存位置 ---
    title("步驟 3／3　照片要存到哪裡")
    default_out = cfg.get("output_dir") or config.DEFAULTS["output_dir"]
    print("\n  預設：%s" % default_out)
    out = ask("  直接按 Enter 用預設，或貼上你要的資料夾路徑：\n  > ", default_out)
    out = os.path.normpath(out.strip('"'))

    cfg["api_key"] = key
    cfg["folder_id"] = folder_id
    cfg["output_dir"] = out
    if config.save(cfg):
        print("\n  ✔ 設定已寫入 settings.json")
    else:
        print("\n  ✗ 設定寫不進去（資料夾唯讀？），請在程式視窗裡自己填一次。")

    title("設定完成")
    print("""
  以後要用，就雙擊資料夾裡的【執行.bat】。

  操作順序：讀取日期 → 勾選要下載的日期 → 開始下載
  照片會存成  %s\\20260830\\  ，同一天另外打包成 20260830.zip
""" % out)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消。")
