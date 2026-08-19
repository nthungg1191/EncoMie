"""
PyQt6 License Dialogs for EncoMie Desktop App.
Provides activation input dialog and license info status dialog.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QFrame, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon

from core.license_manager import LicenseManager, LicenseStatus, LicenseInfo


class ActivateWorker(QThread):
    finished_signal = pyqtSignal(object)

    def __init__(self, manager: LicenseManager, key: str):
        super().__init__()
        self.manager = manager
        self.key = key

    def run(self):
        info = self.manager.activate(self.key)
        self.finished_signal.emit(info)


class LicenseWindow(QDialog):
    """
    Activation Dialog for entering and activating License Keys.
    """

    def __init__(self, manager: LicenseManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.result_info: LicenseInfo | None = None
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("Kích Hoạt Bản Quyền - EncoMie")
        self.setFixedSize(480, 320)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QLabel {
                color: #e2e8f0;
            }
            QLineEdit {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 10px 14px;
                color: #38bdf8;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 14px;
                font-weight: bold;
            }
            QLineEdit:focus {
                border: 1px solid #38bdf8;
            }
            QPushButton#btnActivate {
                background: linear-gradient(135deg, #3b82f6, #8b5cf6);
                background-color: #3b82f6;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton#btnActivate:hover {
                background-color: #2563eb;
            }
            QPushButton#btnCancel {
                background-color: #334155;
                color: #94a3b8;
                border: none;
                border-radius: 8px;
                padding: 12px 20px;
                font-size: 13px;
            }
            QPushButton#btnCancel:hover {
                background-color: #475569;
                color: #ffffff;
            }
            QProgressBar {
                border: none;
                background-color: #1e293b;
                height: 4px;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #38bdf8;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        # Header Title
        title_lbl = QLabel("Vui Lòng Nhập License Key", self)
        title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title_lbl)

        desc_lbl = QLabel("Nhập mã kích hoạt của bạn (Ví dụ: ENCO-XXXX-XXXX-XXXX)", self)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 12px; color: #94a3b8;")
        layout.addWidget(desc_lbl)

        # Key Input
        self.key_edit = QLineEdit(self)
        self.key_edit.setPlaceholderText("ENCO-XXXX-XXXX-XXXX")
        self.key_edit.setMaxLength(36)
        layout.addWidget(self.key_edit)

        # Status / Error Label
        self.status_lbl = QLabel("", self)
        self.status_lbl.setStyleSheet("font-size: 12px; color: #ef4444;")
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        # Progress Bar (hidden by default)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.btn_cancel = QPushButton("Hủy", self)
        self.btn_cancel.setObjectName("btnCancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_activate = QPushButton("Kích Hoạt", self)
        self.btn_activate.setObjectName("btnActivate")
        self.btn_activate.clicked.connect(self._start_activation)
        btn_layout.addWidget(self.btn_activate)

        layout.addLayout(btn_layout)

    def _start_activation(self):
        key = self.key_edit.text().strip()
        if not key:
            self.status_lbl.setText("Vui lòng nhập License Key.")
            return

        self.status_lbl.setText("")
        self.btn_activate.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setVisible(True)

        self.worker = ActivateWorker(self.manager, key)
        self.worker.finished_signal.connect(self._on_activation_finished)
        self.worker.start()

    def _on_activation_finished(self, info: LicenseInfo):
        self.progress_bar.setVisible(False)
        self.btn_activate.setEnabled(True)
        self.btn_cancel.setEnabled(True)

        if info.status == LicenseStatus.VALID:
            self.result_info = info
            QMessageBox.information(
                self,
                "Thành Công",
                "Kích hoạt bản quyền ứng dụng EncoMie thành công!"
            )
            self.accept()
        elif info.status == LicenseStatus.REVOKED:
            self.status_lbl.setText("License key này đã bị thu hồi.")
        elif info.status == LicenseStatus.EXPIRED:
            self.status_lbl.setText("License key này đã hết hạn sử dụng.")
        elif info.status == LicenseStatus.SERVER_ERROR:
            self.status_lbl.setText("Không thể kết nối đến máy chủ xác thực. Vui lòng kiểm tra lại mạng.")
        else:
            msg = info.raw_data.get("error", {}).get("message", "License Key không hợp lệ hoặc đã dùng ở máy khác.")
            self.status_lbl.setText(msg)


class LicenseInfoDialog(QDialog):
    """
    Dialog displaying active license information and Machine HWID.
    """

    def __init__(self, manager: LicenseManager, info: LicenseInfo, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.info = info
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("Thông Tin Bản Quyền - EncoMie")
        self.setFixedSize(440, 300)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QLabel {
                color: #cbd5e1;
                font-size: 13px;
            }
            QPushButton#btnDeactivate {
                background-color: rgba(239, 68, 68, 0.2);
                border: 1px solid rgba(239, 68, 68, 0.4);
                color: #fca5a5;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 12px;
            }
            QPushButton#btnDeactivate:hover {
                background-color: rgba(239, 68, 68, 0.4);
            }
            QPushButton#btnClose {
                background-color: #334155;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 8px 20px;
                font-weight: bold;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("Thông Tin Bản Quyền App", self)
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        frame = QFrame(self)
        frame.setStyleSheet("background-color: #1e293b; border-radius: 8px; padding: 12px;")
        f_lay = QVBoxLayout(frame)
        f_lay.setSpacing(8)

        status_text = "Hợp lệ (Active)" if self.info.is_valid else self.info.status.value.upper()
        expires = self.info.expires_at.strftime("%d/%m/%Y") if self.info.expires_at else "Vĩnh viễn (Lifetime)"
        machine_preview = f"{self.info.machine_id[:8]}...{self.info.machine_id[-4:]}" if self.info.machine_id else "-"

        f_lay.addWidget(QLabel(f"<b>License Key:</b> <font color='#38bdf8'>{self.info.key or 'N/A'}</font>"))
        f_lay.addWidget(QLabel(f"<b>Trạng thái:</b> <font color='#10b981'>{status_text}</font>"))
        f_lay.addWidget(QLabel(f"<b>Thời hạn:</b> {expires}"))
        f_lay.addWidget(QLabel(f"<b>Mã máy (HWID):</b> {machine_preview}"))

        layout.addWidget(frame)
        layout.addStretch()

        btn_lay = QHBoxLayout()
        btn_deact = QPushButton("Hủy Kích Hoạt Máy", self)
        btn_deact.setObjectName("btnDeactivate")
        btn_deact.clicked.connect(self._deactivate)
        btn_lay.addWidget(btn_deact)

        btn_lay.addStretch()

        btn_close = QPushButton("Đóng", self)
        btn_close.setObjectName("btnClose")
        btn_close.clicked.connect(self.accept)
        btn_lay.addWidget(btn_close)

        layout.addLayout(btn_lay)

    def _deactivate(self):
        reply = QMessageBox.question(
            self,
            "Xác Nhận Hủy Kích Hoạt",
            "Bạn có chắc chắn muốn hủy kích hoạt bản quyền trên máy tính này?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.manager.deactivate()
            QMessageBox.information(self, "Đã Hủy", "Bản quyền đã được hủy kích hoạt thành công!")
            self.accept()
