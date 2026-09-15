# -*- coding: utf-8 -*-
"""下載失敗時跑這支，看清楚 Google 到底回了什麼。

    python 診斷.py

會拿最新一個日期資料夾裡的第一張照片，用四種組合各試一次：
  端點（API / 公開下載）× User-Agent（python-requests 預設 / 瀏覽器）
然後告訴你哪一種能通。把輸出整段複製回報即可。
"""
import json
import sys

import requests

import config
from drive_client import API_FILES, UC_DOWNLOAD, BROWSER_UA, DriveClient

LINE = "─" * 62


def probe(label, url, params, ua):
    s = requests.Session()
    if ua:
        s.headers.update({"User-Agent": ua, "Accept": "*/*"})
    try:
        r = s.get(url, params=params, timeout=60, stream=True)
    except requests.RequestException as e:
        print("  %-34s 連不上（%s）" % (label, e.__class__.__name__))
        return False
    ct = r.headers.get("content-type", "")
    ok = r.status_code == 200 and "text/html" not in ct.lower()
    head = next(r.iter_content(chunk_size=120), b"") if ok else b""
    note = ""
    if not ok:
        body = (r.text or "")[:400]
        if "Sorry" in body or "unusual traffic" in body:
            note = "  ← 防濫用頁（Sorry...）"
        elif "text/html" in ct.lower():
            note = "  ← 回了網頁"
    r.close()
    print("  %-34s HTTP %s  %-26s %s%s"
          % (label, r.status_code, ct[:26], "✔ 拿到檔案" if ok else "✗", note))
    if ok:
        print("      前幾個位元組：%s" % head[:16])
    return ok


def main():
    cfg = config.load()
    key, folder = cfg.get("api_key", ""), cfg.get("folder_id", "")
    if not key:
        print("settings.json 裡沒有金鑰，請先跑 安裝.bat。")
        return

    print(LINE)
    print("  施工照片下載工具　連線診斷")
    print(LINE)
    print("  金鑰長度 %d（末四碼 %s）" % (len(key), key[-4:]))

    c = DriveClient(key, folder)
    print("\n[1] 列目錄")
    try:
        folders = c.list_date_folders()
    except Exception as e:
        print("  ✗ 失敗：%s" % e)
        print("\n  列目錄就不通了，先確認金鑰與 Drive API 是否啟用。")
        return
    print("  ✔ %d 個日期資料夾，最新：%s" % (len(folders), folders[0]["label"] if folders else "無"))
    if not folders:
        return

    photos = c.list_photos(folders[0]["id"])
    print("  ✔ %s 有 %d 張照片" % (folders[0]["label"], len(photos)))
    if not photos:
        return
    p = photos[0]
    print("  測試對象：%s（%s bytes）" % (p["name"], p["size"]))

    print("\n[2] 下載測試")
    api_params = {"alt": "media", "key": key, "supportsAllDrives": "true"}
    uc_params = {"id": p["id"], "export": "download", "authuser": "0"}
    results = {
        "api+預設UA": probe("API 端點 ／ requests 預設 UA", API_FILES + "/" + p["id"], api_params, None),
        "api+瀏覽器UA": probe("API 端點 ／ 瀏覽器 UA", API_FILES + "/" + p["id"], api_params, BROWSER_UA),
        "uc+預設UA": probe("公開下載端點 ／ requests 預設 UA", UC_DOWNLOAD, uc_params, None),
        "uc+瀏覽器UA": probe("公開下載端點 ／ 瀏覽器 UA", UC_DOWNLOAD, uc_params, BROWSER_UA),
    }

    print("\n" + LINE)
    good = [k for k, v in results.items() if v]
    uc_ok = results["uc+預設UA"] or results["uc+瀏覽器UA"]
    api_ok = results["api+預設UA"] or results["api+瀏覽器UA"]
    if not good:
        print("  四種都被擋。多半是這個網路的對外 IP 被 Google 暫時限流，")
        print("  等 10~30 分鐘、或換一條網路（手機熱點）再跑一次這支診斷。")
    elif uc_ok:
        print("  正常。程式預設就是先打「公開下載端點」這條。")
        if not api_ok:
            print("  （API 端點在這條網路被擋，屬已知狀況，程式會自動跳過它。）")
    elif api_ok:
        print("  這台只有 API 端點通、公開下載端點不通 —— 跟工地網路相反。")
        print("  程式第一張照片會多試一次才切過去，之後就記住了，不用改設定。")
    print("\n  可以通的組合：%s" % ("、".join(good) if good else "無"))
    print(LINE)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消。")
