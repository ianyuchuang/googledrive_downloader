# -*- coding: utf-8 -*-
"""離線煙霧測試：不連網，驗證介面能建起來、勾選與打包邏輯正確。"""
import io, os, sys, zipfile, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

import drive_client, downloader, ui_main

# 1) 連結解析
assert drive_client.parse_folder_id(
    "https://drive.google.com/drive/folders/ABC123?usp=drive_link") == "ABC123"
assert drive_client.parse_folder_id("ABC123") == "ABC123"
print("1 連結解析 ok")

# 2) 日期資料夾過濾與排序（用假的 _list_children）
c = drive_client.DriveClient("k", "f")
c._list_children = lambda pid, extra_q="": [
    {"id": "a", "name": "20260830", "mimeType": drive_client.FOLDER_MIME},
    {"id": "b", "name": "20260731", "mimeType": drive_client.FOLDER_MIME},
    {"id": "c", "name": "20261332", "mimeType": drive_client.FOLDER_MIME},  # 不合法日期
    {"id": "d", "name": "備份",      "mimeType": drive_client.FOLDER_MIME},  # 非日期
    {"id": "e", "name": "20260901", "mimeType": drive_client.FOLDER_MIME},
]
rows = c.list_date_folders()
assert [r["date"] for r in rows] == ["20260901", "20260830", "20260731"], rows
assert rows[0]["label"] == "2026-09-01"
print("2 日期過濾與排序 ok", [r["label"] for r in rows])

# 3) 照片過濾（排除資料夾與 Google 文件）
c._list_children = lambda pid, extra_q="": [
    {"id": "1", "name": "b.jpg", "mimeType": "image/jpeg", "size": "10"},
    {"id": "2", "name": "a.jpg", "mimeType": "image/jpeg", "size": "20"},
    {"id": "3", "name": "sub",   "mimeType": drive_client.FOLDER_MIME},
    {"id": "4", "name": "doc",   "mimeType": "application/vnd.google-apps.document"},
]
ph = c.list_photos("x")
assert [p["name"] for p in ph] == ["a.jpg", "b.jpg"], ph
assert ph[0]["size"] == 20
print("3 照片過濾 ok")

# 4) 檔名清理
assert downloader.safe_name('a:b/c*d.jpg') == "a_b_c_d.jpg"
print("4 檔名清理 ok")

# 5) 下載＋打包全流程（把 client 換成假的）
tmp = tempfile.mkdtemp()
class FakeClient(object):
    def list_photos(self, fid):
        return [{"id": "p1", "name": "one.jpg", "mimeType": "image/jpeg", "size": 5},
                {"id": "p2", "name": "two.jpg", "mimeType": "image/jpeg", "size": 5}]
    def download(self, fid, dest, chunk_cb=None):
        with open(dest, "wb") as f:
            f.write(b"12345")
        return 5

app = QApplication(sys.argv)
w = downloader.DownloadWorker(FakeClient(),
                              [{"date": "20260830", "label": "2026-08-30", "id": "x"}],
                              tmp, make_zip=True, skip_existing=True)
result = {}
w.finished_all.connect(lambda a, b, cc: result.update(ok=a, skip=b, fail=cc))
w.failed.connect(lambda m: result.update(err=m))
w.run()   # 直接同步跑，不開執行緒
assert "err" not in result, result
assert result == {"ok": 2, "skip": 0, "fail": 0}, result
assert sorted(os.listdir(os.path.join(tmp, "20260830"))) == ["one.jpg", "two.jpg"]
zp = os.path.join(tmp, "20260830.zip")
assert os.path.exists(zp)
with zipfile.ZipFile(zp) as z:
    assert sorted(z.namelist()) == ["20260830/one.jpg", "20260830/two.jpg"], z.namelist()
print("5 下載＋打包 ok")

# 6) 第二次跑：已存在且大小相同 → 全部跳過
result.clear()
w2 = downloader.DownloadWorker(FakeClient(),
                               [{"date": "20260830", "label": "2026-08-30", "id": "x"}],
                               tmp, make_zip=True, skip_existing=True)
w2.finished_all.connect(lambda a, b, cc: result.update(ok=a, skip=b, fail=cc))
w2.run()
assert result == {"ok": 0, "skip": 2, "fail": 0}, result
print("6 重複下載跳過 ok")
shutil.rmtree(tmp)

# 7) 介面建得起來，勾選按鈕會動
win = ui_main.MainWindow()
win._on_dates([{"date": "2026083%d" % i, "label": "2026-08-3%d" % i, "id": str(i)}
               for i in range(9)])
assert win.list_dates.count() == 9
win.select_all();     assert len(win.checked_dates()) == 9
win.select_none();    assert len(win.checked_dates()) == 0
win.select_recent7(); assert len(win.checked_dates()) == 7
win.select_invert();  assert len(win.checked_dates()) == 2
print("7 介面與勾選 ok，狀態列：", win.lbl_count.text())


# ---------- 以下針對「Sorry... 防濫用頁」的處理 ----------

SORRY = ('<html><head><title>Sorry...</title></head><body>'
         'Our systems have detected unusual traffic.</body></html>')

class FakeResp(object):
    def __init__(self, status=200, ctype="image/jpeg", body=b"BINARYDATA", text=""):
        self.status_code = status
        self.headers = {"content-type": ctype}
        self._body = body
        self.text = text
    def iter_content(self, chunk_size=1):
        yield self._body
    def close(self): pass
    def json(self): return {}

class FakeSession(object):
    """照腳本依序回應，並記下每次呼叫的 url 與 params。"""
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.headers = {}
    def get(self, url, params=None, timeout=None, stream=False):
        self.calls.append((url, dict(params or {})))
        return self.script.pop(0)

drive_client.time.sleep = lambda *a: None      # 測試不要真的等
downloader.zipfile = zipfile

# 8) 帶了瀏覽器 User-Agent（不帶就會被判成機器人）
c8 = drive_client.DriveClient("k", "f")
assert "Mozilla" in c8.session.headers["User-Agent"], c8.session.headers
print("8 User-Agent ok")

# 9) 預設就先打公開下載端點（診斷實測：工地網路只有這條通）
tmp = tempfile.mkdtemp()
c9 = drive_client.DriveClient("k", "f")
c9.session = FakeSession([FakeResp(200, "image/jpeg", b"OK!")])
n = c9.download("fid", os.path.join(tmp, "a.jpg"))
assert n == 3, n
assert io.open(os.path.join(tmp, "a.jpg"), "rb").read() == b"OK!"
assert c9.session.calls[0][0] == drive_client.UC_DOWNLOAD, c9.session.calls
assert len(c9.session.calls) == 1, "通了就不該再打第二個端點"
print("9 公開下載端點優先 ok（只打了 1 次）")

# 9b) uc 被擋 → 同一輪立刻改打 API（不是在 uc 上乾等 25 秒）
c9b = drive_client.DriveClient("k", "f")
c9b.session = FakeSession([FakeResp(403, "text/html", text=SORRY),
                           FakeResp(200, "image/jpeg", b"VIA-API")])
c9b.download("fid", os.path.join(tmp, "a2.jpg"))
urls = [u for u, _ in c9b.session.calls]
assert urls == [drive_client.UC_DOWNLOAD, drive_client.API_FILES + "/fid"], urls
assert c9b._preferred == "api", c9b._preferred
print("9b 一輪內換端點、並記住通的那個 ok")

# 9c) 記住之後，下一個檔案直接從 API 開始，不再浪費一次請求
c9b.session = FakeSession([FakeResp(200, "image/jpeg", b"AGAIN")])
c9b.download("fid2", os.path.join(tmp, "a3.jpg"))
assert c9b.session.calls[0][0] == drive_client.API_FILES + "/fid2", c9b.session.calls
print("9c 端點偏好會沿用 ok")

# 10) 大檔的「無法掃描病毒」確認頁 → 自動帶 confirm token 再送
confirm_page = '<form><input name="confirm" value="t123"><input name="uuid" value="u9"></form>'
c10 = drive_client.DriveClient("k", "f")
c10.session = FakeSession([FakeResp(200, "text/html", text=confirm_page),
                           FakeResp(200, "image/jpeg", b"BIGFILE")])
c10.download("fid", os.path.join(tmp, "b.jpg"))
assert c10.session.calls[1][1].get("confirm") == "t123", c10.session.calls[1]
assert c10.session.calls[1][1].get("uuid") == "u9"
assert io.open(os.path.join(tmp, "b.jpg"), "rb").read() == b"BIGFILE"
print("10 病毒掃描確認頁 ok")

# 11) 全部端點都被擋 → 丟 BlockedError，不會留下 .part 假檔
c11 = drive_client.DriveClient("k", "f")
c11.session = FakeSession([FakeResp(403, "text/html", text=SORRY)] * 6)  # 3 輪 × 2 端點
try:
    c11.download("fid", os.path.join(tmp, "c.jpg"))
    raise AssertionError("應該要丟 BlockedError")
except drive_client.BlockedError:
    pass
assert not os.path.exists(os.path.join(tmp, "c.jpg"))
assert not os.path.exists(os.path.join(tmp, "c.jpg.part"))
print("11 全被擋 ok（沒留下半個檔）")

# 12) 連續被擋 5 次 → 整批停下來並給出說明，不硬磨完
class BlockingClient(object):
    def list_photos(self, fid):
        return [{"id": str(i), "name": "p%d.jpg" % i, "mimeType": "image/jpeg", "size": 5}
                for i in range(20)]
    def download(self, fid, dest, chunk_cb=None):
        raise drive_client.BlockedError("Google 回了網頁而不是檔案（防濫用頁）。")

msg = {}
w12 = downloader.DownloadWorker(BlockingClient(),
                                [{"date": "20260831", "label": "2026-08-31", "id": "x"}],
                                tmp, make_zip=False, skip_existing=True)
w12.failed.connect(lambda m: msg.update(text=m))
w12.run()
assert "text" in msg and "防濫用" in msg["text"], msg
print("12 連續被擋會整批停下 ok")
shutil.rmtree(tmp)

print("\n全部通過")
