# -*- coding: utf-8 -*-
"""PyQt5 主視窗。只管畫面與互動，實際工作丟給 drive_client / downloader。"""
import os
import subprocess
import sys

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QCheckBox,
    QProgressBar, QPlainTextEdit, QFileDialog, QMessageBox, QSplitter, QComboBox
)

import config
from drive_client import DriveClient, DriveError
from downloader import DownloadWorker


def human_size(n):
    """1234567 → '1.2 MB'；大小不明回空字串。"""
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%d %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


class ListWorker(QThread):
    """在背景抓資料夾清單，避免按下去畫面卡住。"""
    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, client, parent=None):
        super(ListWorker, self).__init__(parent)
        self.client = client

    def run(self):
        try:
            self.done.emit(self.client.list_items())
        except DriveError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit("%s：%s" % (e.__class__.__name__, e))


class MainWindow(QWidget):
    def __init__(self):
        super(MainWindow, self).__init__()
        self.cfg = config.load()
        self.rows = []             # 目前讀到的項目（還沒排序）
        self.list_worker = None
        self.dl_worker = None
        self._build_ui()
        self._load_settings()
        self._first_run_hint()

    # ---------------- 介面 ----------------

    def _build_ui(self):
        self.setWindowTitle("資料夾檔案下載工具")
        self.resize(880, 640)

        root = QVBoxLayout(self)

        # --- 連線設定 ---
        box_conn = QGroupBox("連線設定")
        g = QGridLayout(box_conn)

        g.addWidget(QLabel("API 金鑰："), 0, 0)
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("Google Cloud 建立的 API 金鑰")
        g.addWidget(self.ed_key, 0, 1)
        self.chk_show_key = QCheckBox("顯示")
        self.chk_show_key.toggled.connect(
            lambda on: self.ed_key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        g.addWidget(self.chk_show_key, 0, 2)

        g.addWidget(QLabel("資料夾："), 1, 0)
        self.ed_folder = QLineEdit()
        self.ed_folder.setPlaceholderText("貼上雲端硬碟資料夾連結，或直接填資料夾 ID")
        g.addWidget(self.ed_folder, 1, 1)
        self.btn_reload = QPushButton("讀取清單")
        self.btn_reload.clicked.connect(self.reload_items)
        g.addWidget(self.btn_reload, 1, 2)
        g.setColumnStretch(1, 1)

        root.addWidget(box_conn)

        # --- 中段：項目清單 + 下載選項 ---
        mid = QSplitter(Qt.Horizontal)

        box_items = QGroupBox("選擇要下載的資料夾或檔案（可複選）")
        v = QVBoxLayout(box_items)
        row_sort = QHBoxLayout()
        row_sort.addWidget(QLabel("排序："))
        self.cmb_sort = QComboBox()
        self.cmb_sort.addItems(["名稱升冪（A→Z）", "名稱降冪（Z→A）"])
        self.cmb_sort.currentIndexChanged.connect(lambda _: self._render_list())
        row_sort.addWidget(self.cmb_sort)
        row_sort.addStretch(1)
        v.addLayout(row_sort)
        self.list_box = QListWidget()
        self.list_box.itemChanged.connect(lambda _: self._update_count())
        v.addWidget(self.list_box)
        row = QHBoxLayout()
        for text, fn in (("全選", self.select_all),
                         ("全不選", self.select_none),
                         ("反選", self.select_invert)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        self.lbl_count = QLabel("尚未讀取")
        v.addWidget(self.lbl_count)
        mid.addWidget(box_items)

        box_opt = QGroupBox("下載選項")
        v2 = QVBoxLayout(box_opt)
        v2.addWidget(QLabel("儲存位置："))
        row2 = QHBoxLayout()
        self.ed_out = QLineEdit()
        row2.addWidget(self.ed_out)
        b_browse = QPushButton("瀏覽…")
        b_browse.clicked.connect(self.choose_output)
        row2.addWidget(b_browse)
        v2.addLayout(row2)

        self.chk_zip = QCheckBox("每個資料夾另外打包成一個 zip")
        self.chk_skip = QCheckBox("已下載過的檔案跳過（大小相同）")
        v2.addWidget(self.chk_zip)
        v2.addWidget(self.chk_skip)
        v2.addWidget(QLabel(
            "檔案會存成：\n"
            "  儲存位置\\資料夾\\…（保留子資料夾）\n"
            "  儲存位置\\資料夾.zip\n"
            "  儲存位置\\單獨勾選的檔案"))
        v2.addStretch(1)

        row3 = QHBoxLayout()
        self.btn_start = QPushButton("開始下載")
        self.btn_start.setMinimumHeight(36)
        self.btn_start.clicked.connect(self.start_download)
        row3.addWidget(self.btn_start)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_download)
        row3.addWidget(self.btn_cancel)
        v2.addLayout(row3)

        self.btn_open = QPushButton("開啟儲存資料夾")
        self.btn_open.clicked.connect(self.open_output)
        v2.addWidget(self.btn_open)

        mid.addWidget(box_opt)
        mid.setStretchFactor(0, 3)
        mid.setStretchFactor(1, 2)
        root.addWidget(mid, 1)

        # --- 進度與訊息 ---
        self.lbl_status = QLabel("就緒")
        root.addWidget(self.lbl_status)
        self.bar = QProgressBar()
        self.bar.setValue(0)
        root.addWidget(self.bar)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(160)
        root.addWidget(self.txt_log)

    # ---------------- 設定 ----------------

    def _load_settings(self):
        self.ed_key.setText(self.cfg["api_key"])
        self.ed_folder.setText(self.cfg["folder_id"])
        self.ed_out.setText(self.cfg["output_dir"])
        self.chk_zip.setChecked(bool(self.cfg["make_zip"]))
        self.chk_skip.setChecked(bool(self.cfg["skip_existing"]))
        self.cmb_sort.setCurrentIndex(1 if self.cfg["sort_desc"] else 0)

    def _first_run_hint(self):
        """還沒設定金鑰時，直接在訊息區講清楚下一步。"""
        if self.cfg.get("api_key"):
            self._log("設定已載入，按「讀取清單」開始。")
            return
        self.lbl_status.setText("還沒設定 API 金鑰")
        self._log(
            "還沒設定 API 金鑰。\n"
            "建議關掉這個視窗，雙擊資料夾裡的「安裝.bat」，\n"
            "它會帶著你一步一步申請並自動填好。\n"
            "（或者你已經有金鑰，直接貼到上面的欄位也可以。）")

    def _save_settings(self):
        self.cfg.update({
            "api_key": self.ed_key.text().strip(),
            "folder_id": self.ed_folder.text().strip(),
            "output_dir": self.ed_out.text().strip(),
            "make_zip": self.chk_zip.isChecked(),
            "skip_existing": self.chk_skip.isChecked(),
            "sort_desc": self.cmb_sort.currentIndex() == 1,
        })
        config.save(self.cfg)

    def closeEvent(self, event):
        if self.dl_worker and self.dl_worker.isRunning():
            if QMessageBox.question(self, "還在下載",
                                    "下載還沒完成，確定要關閉嗎？",
                                    QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No) != QMessageBox.Yes:
                event.ignore()
                return
            self.dl_worker.cancel()
            self.dl_worker.wait(3000)
        self._save_settings()
        event.accept()

    # ---------------- 讀取清單 ----------------

    def _client(self):
        return DriveClient(self.ed_key.text(), self.ed_folder.text())

    def reload_items(self):
        key = self.ed_key.text().strip()
        folder = self.ed_folder.text().strip()
        if not key:
            QMessageBox.warning(self, "缺少 API 金鑰", "請先填入 API 金鑰（申請方式見 README）。")
            return
        if not folder:
            QMessageBox.warning(self, "缺少資料夾", "請填入雲端硬碟資料夾連結或 ID。")
            return
        self._save_settings()
        self.btn_reload.setEnabled(False)
        self.lbl_status.setText("讀取資料夾清單中…")
        self.list_worker = ListWorker(self._client(), self)
        self.list_worker.done.connect(self._on_items)
        self.list_worker.failed.connect(self._on_list_failed)
        self.list_worker.finished.connect(lambda: self.btn_reload.setEnabled(True))
        self.list_worker.start()

    def _on_items(self, rows):
        self.rows = rows
        self.list_box.clear()      # 換了新清單，舊的勾選不沿用
        self._render_list()
        n_dir = sum(1 for r in rows if r["is_folder"])
        msg = "共 %d 個資料夾、%d 個檔案" % (n_dir, len(rows) - n_dir)
        self.lbl_status.setText(msg)
        self._log("讀到 " + msg + "。")
        if not rows:
            QMessageBox.information(self, "資料夾是空的",
                                    "這個資料夾底下沒有可下載的項目。\n"
                                    "（Google 文件、試算表這類線上格式不會列出。）")

    def _on_list_failed(self, msg):
        self.lbl_status.setText("讀取失敗")
        self._log("讀取失敗：" + msg)
        QMessageBox.critical(self, "讀取失敗", msg)

    def _render_list(self):
        """依目前的排序方式重畫清單；資料夾永遠排在檔案前面，已勾選的保持勾選。"""
        checked = {r["id"] for r in self.checked_items()}
        desc = self.cmb_sort.currentIndex() == 1
        rows = sorted(self.rows, key=lambda r: r["name"].lower(), reverse=desc)
        rows.sort(key=lambda r: not r["is_folder"])   # 穩定排序，不會打亂上面的名稱順序

        self.list_box.blockSignals(True)
        self.list_box.clear()
        for r in rows:
            if r["is_folder"]:
                text = "📁  %s" % r["name"]
            else:
                text = "📄  %s    %s" % (r["name"], human_size(r["size"]))
            it = QListWidgetItem(text)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if r["id"] in checked else Qt.Unchecked)
            it.setData(Qt.UserRole, r)
            self.list_box.addItem(it)
        self.list_box.blockSignals(False)
        self._update_count()

    # ---------------- 勾選 ----------------

    def _items(self):
        return [self.list_box.item(i) for i in range(self.list_box.count())]

    def _set_all(self, state):
        self.list_box.blockSignals(True)
        for it in self._items():
            it.setCheckState(state)
        self.list_box.blockSignals(False)
        self._update_count()

    def select_all(self):
        self._set_all(Qt.Checked)

    def select_none(self):
        self._set_all(Qt.Unchecked)

    def select_invert(self):
        self.list_box.blockSignals(True)
        for it in self._items():
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
        self.list_box.blockSignals(False)
        self._update_count()

    def checked_items(self):
        return [it.data(Qt.UserRole) for it in self._items()
                if it.checkState() == Qt.Checked]

    def _update_count(self):
        n = len(self.checked_items())
        total = self.list_box.count()
        self.lbl_count.setText("已勾選 %d / %d 個項目" % (n, total) if total else "尚未讀取")

    # ---------------- 下載 ----------------

    def choose_output(self):
        start = self.ed_out.text().strip() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "選擇儲存位置", start)
        if path:
            self.ed_out.setText(os.path.normpath(path))

    def open_output(self):
        path = self.ed_out.text().strip()
        if not path or not os.path.isdir(path):
            QMessageBox.information(self, "資料夾不存在", "儲存資料夾還沒建立。")
            return
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def start_download(self):
        items = self.checked_items()
        if not items:
            QMessageBox.warning(self, "沒有勾選", "請先勾選要下載的資料夾或檔案。")
            return
        out = self.ed_out.text().strip()
        if not out:
            QMessageBox.warning(self, "沒有儲存位置", "請先選擇儲存位置。")
            return
        try:
            if not os.path.isdir(out):
                os.makedirs(out)
        except OSError as e:
            QMessageBox.critical(self, "無法建立資料夾", str(e))
            return

        self._save_settings()
        self._set_busy(True)
        self.bar.setValue(0)
        self._log("─" * 40)
        self._log("開始下載 %d 個項目 → %s" % (len(items), out))

        self.dl_worker = DownloadWorker(
            self._client(), items, out,
            make_zip=self.chk_zip.isChecked(),
            skip_existing=self.chk_skip.isChecked(),
            parent=self)
        self.dl_worker.log.connect(self._log)
        self.dl_worker.current.connect(self.lbl_status.setText)
        self.dl_worker.file_progress.connect(self._on_progress)
        self.dl_worker.item_done.connect(self._on_item_done)
        self.dl_worker.finished_all.connect(self._on_finished)
        self.dl_worker.failed.connect(self._on_dl_failed)
        self.dl_worker.start()

    def cancel_download(self):
        if self.dl_worker:
            self.dl_worker.cancel()
            self.lbl_status.setText("取消中，等目前這個檔案下載完…")
            self.btn_cancel.setEnabled(False)

    def _set_busy(self, busy):
        self.btn_start.setEnabled(not busy)
        self.btn_reload.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)

    def _on_progress(self, done, total):
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(done)

    def _on_item_done(self, name, n, zip_path):
        if zip_path:
            self._log("✔ %s 完成，%d 個檔案，已打包 %s" % (name, n, os.path.basename(zip_path)))
        elif n:
            self._log("✔ %s 完成，%d 個檔案" % (name, n))
        else:
            self._log("· %s：沒有下載到檔案" % name)

    def _on_finished(self, ok, skipped, failed):
        self._set_busy(False)
        self.lbl_status.setText("完成：下載 %d、跳過 %d、失敗 %d" % (ok, skipped, failed))
        self._log("全部結束：下載 %d、跳過 %d、失敗 %d" % (ok, skipped, failed))

    def _on_dl_failed(self, msg):
        self._set_busy(False)
        self.lbl_status.setText("下載中止")
        self._log("下載中止：" + msg)
        QMessageBox.critical(self, "下載中止", msg)

    def _log(self, text):
        self.txt_log.appendPlainText(text)


def run():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
