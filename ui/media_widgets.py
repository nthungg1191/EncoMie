"""Reusable media selection, pair-table, and background video frame extraction helpers."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from core.app_paths import get_ffmpeg_path, get_ffprobe_path
from core.video_processor import FilePair


class FolderPicker(QWidget):
    """A label + line edit + browse button row."""

    def __init__(self, label: str, placeholder: str = "", parent=None):
        super().__init__(parent)
        self._mode = "folder"
        self._selected_files: list[str] = []
        self._file_filter = "All files (*.*)"
        self._dialog_title = "Chọn file"

        self.setStyleSheet(
            "FolderPicker { background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 4px 6px; }"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        self.lbl = QLabel(label, self)
        self.lbl.setMinimumWidth(max(58, self.lbl.sizeHint().width() + 4))
        self.lbl.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #475569;")

        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setReadOnly(True)
        self.edit.textChanged.connect(self.edit.setToolTip)
        self.edit.setMinimumWidth(84)
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit.setStyleSheet(
            "QLineEdit { font-size: 11px; padding: 5px 8px; background-color: #ffffff; "
            "border: 1px solid #cbd5e1; border-radius: 6px; color: #0f172a; }"
        )

        self.btn = QPushButton("Chọn", self)
        self.btn.setMinimumWidth(56)
        self.btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 5px 8px; background-color: #ffffff; "
            "border: 1px solid #cbd5e1; border-radius: 6px; color: #0f172a; font-weight: 500; }"
            "QPushButton:hover { background-color: #f1f5f9; border-color: #007aff; color: #007aff; }"
        )
        self.btn.clicked.connect(self._browse)

        lay.addWidget(self.lbl)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.btn)

    def set_mode(self, mode: str):
        self._mode = mode
        if mode == "files":
            self._selected_files = []

    def set_file_dialog(self, dialog_title: str, file_filter: str):
        self._dialog_title = dialog_title
        self._file_filter = file_filter

    def _browse(self):
        current = self.edit.text() or os.path.expanduser("~")
        if self._mode == "files":
            if self._selected_files:
                current = str(Path(self._selected_files[0]).parent)
            elif current and Path(current).exists() and Path(current).is_file():
                current = str(Path(current).parent)
            files, _ = QFileDialog.getOpenFileNames(
                self,
                self._dialog_title,
                current,
                self._file_filter,
            )
            if files:
                self._selected_files = files
                if len(files) == 1:
                    self.edit.setText(Path(files[0]).name)
                else:
                    self.edit.setText(f"Đã chọn {len(files)} file")
                if hasattr(self, "_callback"):
                    self._callback(files)
            return

        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục", current)
        if folder:
            self.edit.setText(folder)
            if hasattr(self, "_callback"):
                self._callback(folder)

    def set_callback(self, fn):
        self._callback = fn

    def value(self) -> str:
        try:
            return self.edit.text()
        except Exception:
            return ""

    def set_value(self, v: str):
        try:
            self.edit.setText(v)
        except Exception:
            pass

    def selected_files(self) -> list[str]:
        return list(self._selected_files)

    def set_selected_files(self, files: list[str]):
        self._selected_files = list(files)
        try:
            if not files:
                self.edit.clear()
            elif len(files) == 1:
                self.edit.setText(Path(files[0]).name)
            else:
                self.edit.setText(f"Đã chọn {len(files)} file")
        except Exception:
            pass


class PairTable(QTableWidget):
    """Table showing matched audio↔SRT file pairs."""

    COLS = ["#", "MEDIA", "PHỤ ĐỀ", "TRẠNG THÁI"]

    def __init__(self, parent=None):
        super().__init__(0, len(self.COLS), parent)
        self.setHorizontalHeaderLabels(self.COLS)
        header_tips = ("Số thứ tự", "Tệp audio hoặc video", "Tệp phụ đề SRT", "Trạng thái ghép cặp")
        for column, tip in enumerate(header_tips):
            self.horizontalHeaderItem(column).setToolTip(tip)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(26)
        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hdr.setStretchLastSection(False)
        hdr.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setColumnWidth(0, 42)
        self.setColumnWidth(3, 100)

    def load_pairs(self, pairs: list[FilePair], unchecked_paths: set = None):
        if unchecked_paths is None:
            unchecked_paths = set()
        self.blockSignals(True)
        try:
            self.setRowCount(0)
            for pair in pairs:
                row = self.rowCount()
                self.insertRow(row)

                try:
                    idx_num = int(pair.index)
                    idx_str = str(idx_num)
                except (ValueError, TypeError):
                    idx_str = str(pair.index)

                item_idx = self._cell(idx_str, center=True, checkable=pair.matched)
                if pair.audio_path:
                    item_idx.setData(Qt.ItemDataRole.UserRole, pair.audio_path)
                if pair.audio_path in unchecked_paths:
                    item_idx.setCheckState(Qt.CheckState.Unchecked)
                self.setItem(row, 0, item_idx)

                item_audio = self._cell(Path(pair.audio_path).name if pair.audio_path else "—")
                item_audio.setForeground(QColor("#007aff"))
                self.setItem(row, 1, item_audio)

                item_srt = self._cell(Path(pair.srt_path).name if pair.srt_path else "—")
                item_srt.setForeground(QColor("#007aff"))
                self.setItem(row, 2, item_srt)

                if not pair.audio_path:
                    status_text = "✗ Thiếu file media"
                    status_color = QColor("#ef4444")
                elif not pair.srt_path:
                    status_text = "✗ Thiếu file SRT"
                    status_color = QColor("#ef4444")
                elif pair.error == "Lệch file":
                    status_text = "⚠️ Lệch file"
                    status_color = QColor("#d97706")
                elif pair.matched:
                    status_text = "✓ Khớp"
                    status_color = QColor("#10b981")
                else:
                    status_text = f"✗ {pair.error}"
                    status_color = QColor("#ef4444")

                status_item = self._cell(status_text, center=True)
                status_item.setForeground(status_color)
                self.setItem(row, 3, status_item)
        finally:
            self.blockSignals(False)

    @staticmethod
    def _cell(text: str, center: bool = False, checkable: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        if center:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if checkable:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
        return item


def _extract_video_frame(video_path: str, timestamp: str | None = None) -> QImage | None:
    """
    Extract a single frame from a video file using ffmpeg.
    Returns a QImage, or None on failure.
    Uses the middle of the video by default (more representative than start).
    """
    if not os.path.exists(video_path):
        return None

    ffmpeg_path = get_ffmpeg_path()
    ffprobe_path = get_ffprobe_path()

    try:
        if timestamp is None:
            probe_result = subprocess.run(
                [
                    ffprobe_path, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    video_path,
                ],
                capture_output=True, encoding="utf-8", errors="replace", timeout=10,
            )
            try:
                duration = float(probe_result.stdout.strip())
                timestamp = max(1.0, duration / 2)
            except (ValueError, OSError):
                timestamp = 5.0

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        cmd = [
            ffmpeg_path, "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            tmp_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
        if result.returncode != 0 or not os.path.exists(tmp_path):
            return None

        img = QImage(tmp_path)
        os.unlink(tmp_path)
        return img if not img.isNull() else None
    except Exception:
        return None


class FrameExtractSignals(QObject):
    loaded = pyqtSignal(str, QImage)  # path, image


class FrameExtractTask(QRunnable):
    def __init__(self, video_path: str):
        super().__init__()
        self.video_path = video_path
        self.signals = FrameExtractSignals()

    def run(self):
        img = _extract_video_frame(self.video_path)
        if img and not img.isNull():
            self.signals.loaded.emit(self.video_path, img)
