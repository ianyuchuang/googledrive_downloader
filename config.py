# -*- coding: utf-8 -*-
"""設定的讀寫。

設定檔 settings.json 放在程式同一個資料夾，內容都是純文字，
包含 API 金鑰 —— 所以這個資料夾不要放到公開的地方。
"""
import json
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")

# 照片上傳資料夾 ID 不寫在程式裡（倉庫是公開的），由設定精靈或程式視窗填入 settings.json
DEFAULT_FOLDER_ID = ""

DEFAULTS = {
    "api_key": "",
    "folder_id": DEFAULT_FOLDER_ID,
    "output_dir": os.path.join(os.path.expanduser("~"), "Desktop", "施工照片"),
    "make_zip": True,
    "skip_existing": True,
}


def load():
    """讀設定；檔案不存在或壞掉時回傳預設值，不丟例外。"""
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for k in DEFAULTS:
                if k in saved:
                    data[k] = saved[k]
    except (IOError, OSError, ValueError):
        pass
    return data


def save(data):
    """寫設定；寫不進去就安靜略過（不要因為存設定失敗就中斷下載）。"""
    out = {k: data.get(k, DEFAULTS[k]) for k in DEFAULTS}
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return True
    except (IOError, OSError):
        return False
