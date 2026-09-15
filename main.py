# -*- coding: utf-8 -*-
"""資料夾檔案下載工具 — 進入點。

    python main.py

程式是用 pythonw 啟動的（沒有黑色命令列視窗），所以出錯時看不到訊息，
這裡自己接住例外：寫進 error.log，再用 Windows 對話框顯示。
"""
import os
import sys
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(APP_DIR, "error.log")


def show_error(title, message):
    """沒有主控台也看得到的錯誤提示。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
        return
    except Exception:
        pass
    print("%s\n%s" % (title, message))


def main():
    try:
        from ui_main import run
    except ImportError as e:
        show_error("缺少套件",
                   "少了必要的套件：%s\n\n"
                   "請先雙擊資料夾裡的「安裝.bat」。" % e)
        sys.exit(1)

    try:
        run()
    except SystemExit:
        raise
    except Exception:
        detail = traceback.format_exc()
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(detail + "\n")
        except (IOError, OSError):
            pass
        show_error("程式發生錯誤",
                   "%s\n\n完整訊息已寫入 error.log" % detail.strip().splitlines()[-1])
        sys.exit(1)


if __name__ == "__main__":
    main()
