# -*- coding: utf-8 -*-
"""下載與打包。

跑在背景執行緒，只透過 Qt 訊號跟介面溝通；下載與打包的規則都在這裡，
介面那一層不需要知道細節。
"""
import os
import zipfile

from PyQt5.QtCore import QThread, pyqtSignal

from drive_client import DriveError, BlockedError

# Windows 檔名不能出現的字元
BAD_CHARS = '<>:"/\\|?*'


def safe_name(name):
    out = "".join("_" if ch in BAD_CHARS else ch for ch in name)
    out = out.strip().rstrip(".")
    return out or "unnamed"


def unique_path(folder, name):
    """同名檔案自動加 (2)、(3)，不覆蓋。"""
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(name)
    i = 2
    while True:
        cand = os.path.join(folder, "%s (%d)%s" % (stem, i, ext))
        if not os.path.exists(cand):
            return cand
        i += 1


class DownloadWorker(QThread):
    """把勾選的項目一個一個下載下來。

    勾的是資料夾 → 整個資料夾（含子資料夾）存到 儲存位置\\資料夾名\\，保留原本的層次，
                   可另外打包成 儲存位置\\資料夾名.zip
    勾的是檔案   → 直接存到 儲存位置\\ 底下
    """

    log = pyqtSignal(str)                 # 一行訊息
    file_progress = pyqtSignal(int, int)  # 已完成檔數, 總檔數
    current = pyqtSignal(str)             # 目前在做什麼
    item_done = pyqtSignal(str, int, str) # 項目名稱, 檔案數, zip 路徑（沒打包就空字串）
    finished_all = pyqtSignal(int, int, int)  # 下載, 跳過, 失敗
    failed = pyqtSignal(str)              # 整批中止的原因

    # 連續被 Google 擋這麼多次就整批停下來，不要傻傻磨完幾百個檔案全部失敗
    MAX_CONSECUTIVE_BLOCKS = 5

    def __init__(self, client, items, output_dir, make_zip=True, skip_existing=True, parent=None):
        super(DownloadWorker, self).__init__(parent)
        self.client = client
        self.items = items            # [{'id','name','is_folder','size',...}]
        self.output_dir = output_dir
        self.make_zip = make_zip
        self.skip_existing = skip_existing
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _plan_item(self, item):
        """回傳這個項目要下載的 [(存放資料夾, 檔案)]。"""
        if not item["is_folder"]:
            return [(self.output_dir, item)]
        base = os.path.join(self.output_dir, safe_name(item["name"]))
        return [(os.path.join(base, *[safe_name(p) for p in parts]), f)
                for parts, f in self.client.walk(item["id"])]

    # ---------- 主流程 ----------

    def run(self):
        n_ok = n_skip = n_fail = 0
        blocks = 0          # 連續被防濫用頁擋掉的次數
        try:
            # 先把每個資料夾有哪些檔案問清楚，才算得出總進度
            plan = []
            total_files = 0
            for it in self.items:
                if self._cancel:
                    break
                if it["is_folder"]:
                    self.current.emit("讀取 %s 的檔案清單…" % it["name"])
                files = self._plan_item(it)
                plan.append((it, files))
                total_files += len(files)
                if it["is_folder"]:
                    self.log.emit("%s：%d 個檔案" % (it["name"], len(files)))

            if self._cancel:
                self.log.emit("已取消。")
                self.finished_all.emit(n_ok, n_skip, n_fail)
                return

            self.file_progress.emit(0, total_files)
            done = 0

            for it, files in plan:
                if self._cancel:
                    break
                saved = []

                for dest_dir, f in files:
                    if self._cancel:
                        break
                    name = safe_name(f["name"])
                    target = os.path.join(dest_dir, name)

                    # 已存在且大小相同就跳過
                    if self.skip_existing and os.path.exists(target):
                        same = f["size"] is None or os.path.getsize(target) == f["size"]
                        if same:
                            saved.append(target)
                            n_skip += 1
                            done += 1
                            self.file_progress.emit(done, total_files)
                            continue

                    self.current.emit(os.path.relpath(target, self.output_dir))
                    try:
                        os.makedirs(dest_dir, exist_ok=True)
                        if not self.skip_existing:
                            target = unique_path(dest_dir, name)
                        self.client.download(f["id"], target)
                        saved.append(target)
                        n_ok += 1
                        blocks = 0
                    except BlockedError as e:
                        n_fail += 1
                        blocks += 1
                        self.log.emit("  ✗ %s：%s" % (name, e))
                        if blocks >= self.MAX_CONSECUTIVE_BLOCKS:
                            self.failed.emit(
                                "Google 連續 %d 次回防濫用頁面，已經停下來。\n\n"
                                "這通常是短時間抓太多檔案被暫時擋住，"
                                "等 10~30 分鐘再試多半就好了。\n"
                                "已經下載好的檔案都留著，重新開始時會自動跳過。"
                                % blocks)
                            return
                    except (DriveError, IOError, OSError) as e:
                        n_fail += 1
                        self.log.emit("  ✗ %s：%s" % (name, e))
                    done += 1
                    self.file_progress.emit(done, total_files)

                if self._cancel:
                    break

                zip_path = ""
                if it["is_folder"] and self.make_zip and saved:
                    self.current.emit("打包 %s.zip…" % safe_name(it["name"]))
                    try:
                        zip_path = self._make_zip(it["name"], saved)
                    except (IOError, OSError) as e:
                        self.log.emit("  ✗ 打包 %s 失敗：%s" % (it["name"], e))
                        zip_path = ""
                self.item_done.emit(it["name"], len(saved), zip_path)

            if self._cancel:
                self.log.emit("已取消。")
            self.finished_all.emit(n_ok, n_skip, n_fail)

        except DriveError as e:
            self.failed.emit(str(e))
        except Exception as e:  # 不讓背景執行緒無聲無息地死掉
            self.failed.emit("%s：%s" % (e.__class__.__name__, e))

    # ---------- 打包 ----------

    def _make_zip(self, folder_name, files):
        """一個資料夾一個 zip，放在儲存位置底下（跟資料夾同層）。"""
        zip_path = os.path.join(self.output_dir, "%s.zip" % safe_name(folder_name))
        tmp = zip_path + ".part"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                if not os.path.exists(f):
                    continue
                # 壓縮檔裡保留 資料夾名/子資料夾/檔案 這層，解開後不會散一地
                zf.write(f, os.path.relpath(f, self.output_dir))
        if os.path.exists(zip_path):
            os.remove(zip_path)
        os.rename(tmp, zip_path)
        return zip_path
