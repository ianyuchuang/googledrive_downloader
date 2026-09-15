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
    """把選到的日期一天一天下載下來，每天結束後（可選）打包成 zip。"""

    log = pyqtSignal(str)                 # 一行訊息
    file_progress = pyqtSignal(int, int)  # 已完成檔數, 總檔數
    current = pyqtSignal(str)             # 目前在做什麼
    date_done = pyqtSignal(str, int, str) # 日期, 張數, zip 路徑（沒打包就空字串）
    finished_all = pyqtSignal(int, int, int)  # 下載, 跳過, 失敗
    failed = pyqtSignal(str)              # 整批中止的原因

    # 連續被 Google 擋這麼多次就整批停下來，不要傻傻磨完幾百張全部失敗
    MAX_CONSECUTIVE_BLOCKS = 5

    def __init__(self, client, dates, output_dir, make_zip=True, skip_existing=True, parent=None):
        super(DownloadWorker, self).__init__(parent)
        self.client = client
        self.dates = dates            # [{'date','label','id'}]
        self.output_dir = output_dir
        self.make_zip = make_zip
        self.skip_existing = skip_existing
        self._cancel = False

    def cancel(self):
        self._cancel = True

    # ---------- 主流程 ----------

    def run(self):
        n_ok = n_skip = n_fail = 0
        blocks = 0          # 連續被防濫用頁擋掉的次數
        try:
            # 先把每一天有哪些檔案問清楚，才算得出總進度
            plan = []
            total_files = 0
            for d in self.dates:
                if self._cancel:
                    break
                self.current.emit("讀取 %s 的檔案清單…" % d["label"])
                photos = self.client.list_photos(d["id"])
                plan.append((d, photos))
                total_files += len(photos)
                self.log.emit("%s：%d 張" % (d["label"], len(photos)))

            if self._cancel:
                self.log.emit("已取消。")
                self.finished_all.emit(n_ok, n_skip, n_fail)
                return

            self.file_progress.emit(0, total_files)
            done = 0

            for d, photos in plan:
                if self._cancel:
                    break
                day_dir = os.path.join(self.output_dir, d["date"])
                try:
                    os.makedirs(day_dir)
                except OSError:
                    if not os.path.isdir(day_dir):
                        raise
                saved = []

                for p in photos:
                    if self._cancel:
                        break
                    name = safe_name(p["name"])
                    target = os.path.join(day_dir, name)

                    # 已存在且大小相同就跳過
                    if self.skip_existing and os.path.exists(target):
                        same = p["size"] is None or os.path.getsize(target) == p["size"]
                        if same:
                            saved.append(target)
                            n_skip += 1
                            done += 1
                            self.file_progress.emit(done, total_files)
                            continue
                    if not self.skip_existing:
                        target = unique_path(day_dir, name)

                    self.current.emit("%s / %s" % (d["label"], name))
                    try:
                        self.client.download(p["id"], target)
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
                if self.make_zip and saved:
                    self.current.emit("打包 %s.zip…" % d["date"])
                    try:
                        zip_path = self._make_zip(day_dir, d["date"], saved)
                    except (IOError, OSError) as e:
                        self.log.emit("  ✗ 打包 %s 失敗：%s" % (d["date"], e))
                        zip_path = ""
                self.date_done.emit(d["label"], len(saved), zip_path)

            if self._cancel:
                self.log.emit("已取消。")
            self.finished_all.emit(n_ok, n_skip, n_fail)

        except DriveError as e:
            self.failed.emit(str(e))
        except Exception as e:  # 不讓背景執行緒無聲無息地死掉
            self.failed.emit("%s：%s" % (e.__class__.__name__, e))

    # ---------- 打包 ----------

    def _make_zip(self, day_dir, date_str, files):
        """一個日期一個 zip，放在輸出資料夾下（跟日期子資料夾同層）。"""
        zip_path = os.path.join(self.output_dir, "%s.zip" % date_str)
        tmp = zip_path + ".part"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                if not os.path.exists(f):
                    continue
                # 壓縮檔裡保留 20260830/xxx.jpg 這層，解開後不會散一地
                zf.write(f, os.path.join(date_str, os.path.basename(f)))
        if os.path.exists(zip_path):
            os.remove(zip_path)
        os.rename(tmp, zip_path)
        return zip_path
