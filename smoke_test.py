# -*- coding: utf-8 -*-
"""離線煙霧測試：不連網，驗證介面能建起來、勾選與打包邏輯正確。"""
import io, os, sys, zipfile, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

import drive_client, downloader, ui_main

FOLDER = drive_client.FOLDER_MIME

# 1) 連結解析
assert drive_client.parse_folder_id(
    "https://drive.google.com/drive/folders/ABC123?usp=drive_link") == "ABC123"
assert drive_client.parse_folder_id("ABC123") == "ABC123"
print("1 連結解析 ok")

# 2) 列項目：排除 Google 文件、資料夾排前面、依名稱排序（不分大小寫）
c = drive_client.DriveClient("k", "f")
c._list_children = lambda pid, extra_q="": [
    {"id": "1", "name": "b.jpg",    "mimeType": "image/jpeg", "size": "10"},
    {"id": "2", "name": "A.pdf",    "mimeType": "application/pdf", "size": "20"},
    {"id": "3", "name": "sub",      "mimeType": FOLDER},
    {"id": "4", "name": "doc",      "mimeType": "application/vnd.google-apps.document"},
    {"id": "5", "name": "20260830", "mimeType": FOLDER},
]
rows = c.list_items()
assert [r["name"] for r in rows] == ["20260830", "sub", "A.pdf", "b.jpg"], rows
assert rows[0]["is_folder"] and not rows[2]["is_folder"]
assert rows[2]["size"] == 20 and rows[0]["size"] is None
print("2 列項目與排序 ok", [r["name"] for r in rows])

# 3) 遞迴走訪：保留子資料夾路徑，繞回自己的資料夾不會無限循環
tree = {
    "a": [{"id": "f1", "name": "1.jpg", "mimeType": "image/jpeg", "size": "1"},
          {"id": "b",  "name": "B",     "mimeType": FOLDER}],
    "b": [{"id": "f2", "name": "2.jpg", "mimeType": "image/jpeg", "size": "2"},
          {"id": "a",  "name": "回到A", "mimeType": FOLDER}],
}
c._list_children = lambda pid, extra_q="": tree.get(pid, [])
got = [("/".join(p), f["name"]) for p, f in c.walk("a")]
assert got == [("B", "2.jpg"), ("", "1.jpg")], got
print("3 遞迴走訪 ok", got)

# 4) 檔名清理
assert downloader.safe_name('a:b/c*d.jpg') == "a_b_c_d.jpg"
print("4 檔名清理 ok")

# 5) 下載＋打包全流程（把 client 換成假的）：勾一個資料夾＋一個單獨檔案
tmp = tempfile.mkdtemp()
class FakeClient(object):
    def walk(self, fid):
        return [((), {"id": "p1", "name": "one.jpg", "size": 5}),
                (("sub:x",), {"id": "p2", "name": "two.jpg", "size": 5})]
    def download(self, fid, dest, chunk_cb=None):
        with open(dest, "wb") as f:
            f.write(b"12345")
        return 5

ITEMS = [{"id": "x", "name": "A",        "is_folder": True,  "size": None},
         {"id": "f", "name": "root.pdf", "is_folder": False, "size": 5}]

app = QApplication(sys.argv)
w = downloader.DownloadWorker(FakeClient(), ITEMS, tmp, make_zip=True, skip_existing=True)
result = {}
w.finished_all.connect(lambda a, b, cc: result.update(ok=a, skip=b, fail=cc))
w.failed.connect(lambda m: result.update(err=m))
w.run()   # 直接同步跑，不開執行緒
assert "err" not in result, result
assert result == {"ok": 3, "skip": 0, "fail": 0}, result
assert os.path.exists(os.path.join(tmp, "A", "one.jpg"))
assert os.path.exists(os.path.join(tmp, "A", "sub_x", "two.jpg"))
assert os.path.exists(os.path.join(tmp, "root.pdf"))
zp = os.path.join(tmp, "A.zip")
assert os.path.exists(zp)
with zipfile.ZipFile(zp) as z:
    assert sorted(z.namelist()) == ["A/one.jpg", "A/sub_x/two.jpg"], z.namelist()
assert not os.path.exists(os.path.join(tmp, "root.pdf.zip")), "單獨的檔案不該打包"
print("5 下載＋打包（含子資料夾、單獨檔案）ok")

# 6) 第二次跑：已存在且大小相同 → 全部跳過
result.clear()
w2 = downloader.DownloadWorker(FakeClient(), ITEMS, tmp, make_zip=True, skip_existing=True)
w2.finished_all.connect(lambda a, b, cc: result.update(ok=a, skip=b, fail=cc))
w2.run()
assert result == {"ok": 0, "skip": 3, "fail": 0}, result
print("6 重複下載跳過 ok")
shutil.rmtree(tmp)

# 7) 介面建得起來，勾選按鈕會動
win = ui_main.MainWindow()
win._on_items([{"id": str(i), "name": "item%d" % i, "is_folder": i < 3,
                "size": None if i < 3 else 1500, "mimeType": ""} for i in range(9)])
assert win.list_box.count() == 9
assert "1.5 KB" in win.list_box.item(8).text(), win.list_box.item(8).text()
win.select_all();    assert len(win.checked_items()) == 9
win.select_none();   assert len(win.checked_items()) == 0
win.list_box.item(0).setCheckState(Qt.Checked)
win.list_box.item(1).setCheckState(Qt.Checked)
win.select_invert(); assert len(win.checked_items()) == 7
print("7 介面與勾選 ok，狀態列：", win.lbl_count.text())

# 7b) 名稱升降冪：資料夾永遠在前，切換排序時勾選不會跑掉
names = lambda: [win.list_box.item(i).data(Qt.UserRole)["name"] for i in range(win.list_box.count())]
win.cmb_sort.setCurrentIndex(0)
assert names() == ["item%d" % i for i in range(9)], names()
win.select_none()
win.list_box.item(0).setCheckState(Qt.Checked)   # item0（資料夾）
win.list_box.item(8).setCheckState(Qt.Checked)   # item8（檔案）
win.cmb_sort.setCurrentIndex(1)
assert names() == ["item2", "item1", "item0", "item8", "item7", "item6", "item5", "item4", "item3"], names()
assert sorted(r["name"] for r in win.checked_items()) == ["item0", "item8"], win.checked_items()
win.cmb_sort.setCurrentIndex(0)
assert names()[0] == "item0" and len(win.checked_items()) == 2
print("7b 名稱升降冪排序 ok")


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

# 9) 預設就先打公開下載端點（診斷實測：有些網路只有這條通）
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
    def walk(self, fid):
        return [((), {"id": str(i), "name": "p%d.jpg" % i, "size": 5}) for i in range(20)]
    def download(self, fid, dest, chunk_cb=None):
        raise drive_client.BlockedError("Google 回了網頁而不是檔案（防濫用頁）。")

msg = {}
w12 = downloader.DownloadWorker(BlockingClient(),
                                [{"id": "x", "name": "A", "is_folder": True, "size": None}],
                                tmp, make_zip=False, skip_existing=True)
w12.failed.connect(lambda m: msg.update(text=m))
w12.run()
assert "text" in msg and "防濫用" in msg["text"], msg
print("12 連續被擋會整批停下 ok")
shutil.rmtree(tmp)

print("\n全部通過")
