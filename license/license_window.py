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
        self.setWindowTitle("Thông Tin Bản Quyền - EncoMie Pro")
        self.setFixedSize(480, 400)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QLabel {
                color: #e2e8f0;
                font-size: 13px;
            }
            QFrame#infoFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 12px;
            }
            QPushButton#btnDeactivate {
                background-color: rgba(239, 68, 68, 0.15);
                border: 1px solid rgba(239, 68, 68, 0.4);
                color: #fca5a5;
                border-radius: 8px;
                padding: 9px 18px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#btnDeactivate:hover {
                background-color: rgba(239, 68, 68, 0.35);
                color: #ffffff;
            }
            QPushButton#btnClose {
                background-color: #3b82f6;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 9px 24px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton#btnClose:hover {
                background-color: #2563eb;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        header_lay = QHBoxLayout()
        icon_lbl = QLabel("🛡️", self)
        icon_lbl.setStyleSheet("font-size: 24px;")
        header_lay.addWidget(icon_lbl)

        title = QLabel("Thông Tin Bản Quyền Ứng Dụng", self)
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #ffffff;")
        header_lay.addWidget(title)
        header_lay.addStretch()
        layout.addLayout(header_lay)

        frame = QFrame(self)
        frame.setObjectName("infoFrame")
        f_lay = QVBoxLayout(frame)
        f_lay.setContentsMargins(18, 16, 18, 16)
        f_lay.setSpacing(12)

        key_val = getattr(self.info, 'key', '') or 'Chưa xác định'
        
        # Determine status icon, text & color dynamically based on LicenseStatus
        status_enum = getattr(self.info, 'status', None)
        if self.info.is_valid or status_enum == LicenseStatus.VALID:
            status_icon = "🟢"
            status_display = "Hợp Lệ (Active)"
            status_color = "#10b981"  # Emerald Green
        elif status_enum == LicenseStatus.EXPIRED:
            status_icon = "🟠"
            status_display = "Đã Hết Hạn (Expired)"
            status_color = "#f97316"  # Vibrant Orange
        elif status_enum == LicenseStatus.REVOKED:
            status_icon = "🔴"
            status_display = "Đã Thu Hồi (Revoked)"
            status_color = "#ef4444"  # Bright Red
        elif status_enum == LicenseStatus.SECURITY_VIOLATION:
            status_icon = "⚠️"
            status_display = "Vi Phạm Bảo Mật (Security Alert)"
            status_color = "#dc2626"  # Dark Red
        elif status_enum == LicenseStatus.NOT_FOUND:
            status_icon = "⚪"
            status_display = "Chưa Kích Hoạt (Not Activated)"
            status_color = "#94a3b8"  # Slate Gray
        elif status_enum == LicenseStatus.SERVER_ERROR:
            status_icon = "🟡"
            status_display = "Không Thể Kết Nối Máy Chủ"
            status_color = "#eab308"  # Amber Yellow
        else:
            status_icon = "🔴"
            status_display = "Không Hợp Lệ (Invalid)"
            status_color = "#ef4444"  # Red
        
        # Format Dates
        created_val = "Không xác định"
        if getattr(self.info, 'created_at', None):
            created_val = self.info.created_at.strftime("%d/%m/%Y")
        elif self.info.raw_data.get("created_at"):
            try:
                dt = datetime.fromisoformat(self.info.raw_data["created_at"].replace("Z", "+00:00"))
                created_val = dt.strftime("%d/%m/%Y")
            except Exception:
                pass

        expires_val = "Vĩnh viễn (Lifetime)"
        if getattr(self.info, 'expires_at', None):
            expires_val = self.info.expires_at.strftime("%d/%m/%Y")
        elif self.info.raw_data.get("expires_at"):
            try:
                dt = datetime.fromisoformat(self.info.raw_data["expires_at"].replace("Z", "+00:00"))
                expires_val = dt.strftime("%d/%m/%Y")
            except Exception:
                pass

        max_devices_val = getattr(self.info, 'max_devices', 1) or 1
        machine_id_val = getattr(self.info, 'machine_id', '') or ''
        machine_preview = f"{machine_id_val[:8]}...{machine_id_val[-4:]}" if len(machine_id_val) > 12 else (machine_id_val or "Chưa bind")

        f_lay.addWidget(QLabel(f"<b>🔑 Mã License Key:</b> &nbsp;<font color='#38bdf8' style='font-family: monospace; font-size: 14px;'>{key_val}</font>"))
        f_lay.addWidget(QLabel(f"<b>{status_icon} Trạng thái:</b> &nbsp;<font color='{status_color}'><b>{status_display}</b></font>"))
        f_lay.addWidget(QLabel(f"<b>📅 Ngày bắt đầu:</b> &nbsp;<font color='#f1f5f9'>{created_val}</font>"))
        f_lay.addWidget(QLabel(f"<b>⏳ Ngày hết hạn:</b> &nbsp;<font color='#f59e0b'><b>{expires_val}</b></font>"))
        f_lay.addWidget(QLabel(f"<b>🖥️ Số thiết bị tối đa:</b> &nbsp;<font color='#f1f5f9'>{max_devices_val} Máy</font>"))
        f_lay.addWidget(QLabel(f"<b>🆔 Mã máy (HWID):</b> &nbsp;<font color='#94a3b8' style='font-family: monospace;'>{machine_preview}</font>"))

        layout.addWidget(frame)

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
