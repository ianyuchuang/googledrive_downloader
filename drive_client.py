# -*- coding: utf-8 -*-
"""Google Drive 存取（只用 API 金鑰，適用「知道連結的人」可存取的資料夾）。

這一層只負責跟 Drive 講話，不碰 UI、不碰執行緒，方便單獨測試：

    python drive_client.py <API金鑰> [資料夾ID或連結]

關於「Sorry...」防濫用頁（2026-08-31，已用 診斷.py 實測確認）
--------------------------------------------------------------
實測結果（某條會擋下載的網路）：

    API 端點 alt=media      ／ 預設 UA    → HTTP 403 防濫用頁
    API 端點 alt=media      ／ 瀏覽器 UA  → HTTP 403 防濫用頁
    drive.usercontent 下載  ／ 預設 UA    → HTTP 200 拿到檔案
    drive.usercontent 下載  ／ 瀏覽器 UA  → HTTP 200 拿到檔案

**跟 User-Agent 無關**，是 www.googleapis.com 的 alt=media 下載
在這條網路上被擋（列目錄同一個網域卻正常，只有下載被擋）。

所以：**公開下載端點排第一順位**，API 端點留作備援
（換一條網路或換一台電腦時，可能反過來是 API 通、uc 不通）。
成功過的端點會被記住，同一次執行不再重複試錯的那個。
"""
import os
import re
import time

import requests

API_FILES = "https://www.googleapis.com/drive/v3/files"
UC_DOWNLOAD = "https://drive.usercontent.google.com/download"
FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_APPS = "application/vnd.google-apps."

CONFIRM_RE = re.compile(r'name="confirm"\s+value="([^"]+)"')
UUID_RE = re.compile(r'name="uuid"\s+value="([^"]+)"')

TIMEOUT = 60
RETRY = 3
ROUND_WAITS = (0, 5, 20)     # 每一輪（把所有端點都試過一次）之間等幾秒
MIN_GAP = 0.35               # 兩次下載之間至少間隔幾秒，別打太快

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class DriveError(Exception):
    """對使用者說得出口的錯誤訊息。"""
    pass


class BlockedError(DriveError):
    """Google 回了防濫用網頁，不是檔案。整批連續發生時應該停下來等。"""
    pass


def parse_folder_id(text):
    """把使用者貼的東西轉成資料夾 ID（完整連結或直接的 ID 都收）。"""
    text = (text or "").strip()
    if not text:
        return ""
    m = re.search(r"/folders/([^/?#]+)", text)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([^&#]+)", text)
    if m:
        return m.group(1)
    return text


def _is_html(resp):
    return "text/html" in resp.headers.get("content-type", "").lower()


def _explain(resp):
    """把 Google 回的錯誤翻成看得懂的話。"""
    if _is_html(resp):
        # 防濫用頁／登入頁之類，body 是一大坨 HTML，直接吐給使用者沒意義
        return ("Google 回了一頁網頁而不是資料（HTTP %d），"
                "通常是短時間內抓太多次被暫時擋下。" % resp.status_code)
    try:
        msg = resp.json().get("error", {}).get("message", "")
    except ValueError:
        msg = (resp.text or "")[:200]

    if resp.status_code == 400 and "API key not valid" in msg:
        return "API 金鑰無效，請確認有沒有複製完整。"
    if resp.status_code == 403:
        if "has not been used" in msg or "disabled" in msg:
            return "這把金鑰的專案還沒啟用 Google Drive API，請到 Google Cloud 主控台啟用後等一兩分鐘再試。"
        if "referer" in msg.lower() or "restrict" in msg.lower():
            return "金鑰被限制條件擋下來了，請把應用程式限制改成「無」。"
        return "存取被拒絕（403）：%s" % msg
    if resp.status_code == 404:
        return "找不到這個檔案或資料夾，請確認共用權限是「知道連結的任何人」。"
    if resp.status_code == 429:
        return "呼叫太頻繁被限流（429），請稍後再試。"
    return "Drive 回應 %s：%s" % (resp.status_code, msg)


class DriveClient(object):
    def __init__(self, api_key, folder_id):
        self.api_key = (api_key or "").strip()
        self.folder_id = parse_folder_id(folder_id)
        self.session = requests.Session()
        # 不帶這個 UA，下載會被 Google 判成機器人
        self.session.headers.update({
            "User-Agent": BROWSER_UA,
            "Accept": "*/*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        })
        self._last_download = 0.0
        # 哪個端點通就記住，之後優先用它。預設 uc：實測有些網路只有它通
        self._preferred = "uc"

    # ---------- 列目錄 ----------

    def _get_json(self, url, params):
        params = dict(params)
        params["key"] = self.api_key
        last = None
        for attempt in range(RETRY):
            try:
                resp = self.session.get(url, params=params, timeout=TIMEOUT)
            except requests.RequestException as e:
                last = DriveError("連不上 Google（%s）" % e.__class__.__name__)
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code == 200 and not _is_html(resp):
                return resp
            retryable = resp.status_code in (429, 500, 502, 503, 504) or _is_html(resp)
            err = BlockedError(_explain(resp)) if _is_html(resp) else DriveError(_explain(resp))
            resp.close()
            if retryable and attempt < RETRY - 1:
                last = err
                time.sleep(3.0 * (attempt + 1))
                continue
            raise err
        raise last or DriveError("無法取得資料")

    def _list_children(self, parent_id, extra_q=""):
        """列出某個資料夾底下的項目，自動翻頁。"""
        q = "'%s' in parents and trashed = false" % parent_id
        if extra_q:
            q += " and " + extra_q
        items = []
        token = None
        while True:
            params = {
                "q": q,
                "fields": "nextPageToken, files(id, name, mimeType, size)",
                "pageSize": 1000,
                "orderBy": "name",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if token:
                params["pageToken"] = token
            data = self._get_json(API_FILES, params).json()
            items.extend(data.get("files", []))
            token = data.get("nextPageToken")
            if not token:
                break
        return items

    def list_items(self, folder_id=None):
        """列出資料夾底下的子資料夾與檔案（沒給就列最上層），資料夾排前面，各自依名稱排序。

        回傳 [{'id','name','mimeType','size','is_folder'}]。
        Google 文件、試算表、捷徑這類線上格式沒有實體檔案可以下載，不列出。
        """
        rows = []
        for f in self._list_children(folder_id or self.folder_id):
            mime = f.get("mimeType", "")
            is_folder = mime == FOLDER_MIME
            if not is_folder and mime.startswith(GOOGLE_APPS):
                continue
            size = f.get("size")
            rows.append({"id": f["id"],
                         "name": f.get("name", f["id"]),
                         "mimeType": mime,
                         "size": int(size) if size is not None else None,
                         "is_folder": is_folder})
        rows.sort(key=lambda r: (not r["is_folder"], r["name"].lower()))
        return rows

    def walk(self, folder_id):
        """遞迴列出資料夾底下所有檔案，回傳 [(子資料夾路徑 tuple, 檔案)]。

        路徑不含 folder_id 本身，例如 (('現場', 'A區'), {...})；
        直接放在 folder_id 底下的檔案路徑是 ()。
        """
        out = []
        seen = set()      # 同一個資料夾可能掛在多個地方，避免繞圈

        def visit(fid, parts):
            if fid in seen:
                return
            seen.add(fid)
            for r in self.list_items(fid):
                if r["is_folder"]:
                    visit(r["id"], parts + (r["name"],))
                else:
                    out.append((parts, r))

        visit(folder_id, ())
        return out

    # ---------- 下載 ----------

    def _endpoints(self, file_id):
        """回傳 [(名稱, 網址, 參數)]，成功過的端點排前面。"""
        eps = {
            "uc": ("uc", UC_DOWNLOAD,
                   {"id": file_id, "export": "download", "authuser": "0"}),
            "api": ("api", API_FILES + "/" + file_id,
                    {"alt": "media", "key": self.api_key, "supportsAllDrives": "true"}),
        }
        order = [self._preferred] + [k for k in ("uc", "api") if k != self._preferred]
        return [eps[k] for k in order]

    def _throttle(self):
        gap = time.time() - self._last_download
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        self._last_download = time.time()

    def _stream(self, url, params, dest_path, chunk_cb, depth=0):
        """把一次回應寫成檔案。回來的是網頁就丟 BlockedError。"""
        resp = self.session.get(url, params=params, timeout=TIMEOUT, stream=True)
        try:
            if resp.status_code != 200:
                raise (BlockedError if _is_html(resp) else DriveError)(_explain(resp))

            if _is_html(resp):
                body = resp.text
                # 大檔會先出現「無法掃描病毒」確認頁，抓 token 再送一次
                m = CONFIRM_RE.search(body)
                if m and depth < 2:
                    p = dict(params)
                    p["confirm"] = m.group(1)
                    mu = UUID_RE.search(body)
                    if mu:
                        p["uuid"] = mu.group(1)
                    resp.close()
                    return self._stream(url, p, dest_path, chunk_cb, depth + 1)
                raise BlockedError("Google 回了網頁而不是檔案（防濫用頁）。")

            tmp = dest_path + ".part"
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        f.write(chunk)
                        if chunk_cb:
                            chunk_cb(len(chunk))
        finally:
            resp.close()

        if os.path.exists(dest_path):
            os.remove(dest_path)
        os.rename(tmp, dest_path)
        return os.path.getsize(dest_path)

    def download(self, file_id, dest_path, chunk_cb=None):
        """下載單一檔案。

        一輪 = 把每個端點各試一次；整輪都失敗才等一下再跑下一輪。
        （不要在同一個端點連等 25 秒 —— 那個端點若是整條網路被擋，
        等再久也一樣，先換另一個端點才划算。）
        """
        self._throttle()
        last = None
        for wait in ROUND_WAITS:
            if wait:
                time.sleep(wait)
            for name, url, params in self._endpoints(file_id):
                try:
                    n = self._stream(url, params, dest_path, chunk_cb)
                    self._preferred = name        # 記住通的那個
                    return n
                except BlockedError as e:
                    last = e
                except DriveError as e:
                    last = e
                except requests.RequestException as e:
                    last = DriveError("連線中斷（%s）" % e.__class__.__name__)
        raise last or DriveError("下載失敗")

    # ---------- 測試 ----------

    def check(self):
        if not self.api_key:
            raise DriveError("還沒填 API 金鑰。")
        if not self.folder_id:
            raise DriveError("還沒填資料夾 ID 或連結。")
        return len(self.list_items())


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法：python drive_client.py <API金鑰> <資料夾ID或連結>")
        sys.exit(1)
    c = DriveClient(sys.argv[1], sys.argv[2])
    items = c.list_items()
    print("最上層 %d 個項目" % len(items))
    for r in items[:20]:
        print("  [資料夾]" if r["is_folder"] else "  [檔案]  ", r["name"], r["size"] or "")
