"""
Main window for Auto Video Editor.
Layout (3-panel horizontal):
  Left   — folder pickers + file pair table
  Middle — subtitle style controls + preview
  Right  — render settings + FFmpeg log + render controls
"""

import json
import os
import random
import sys
from pathlib import Path

# Ensure project root is on the path whether this file is run directly
# (python ui/main_window.py) or imported from main.py
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QComboBox, QSpinBox, QDoubleSpinBox, QAbstractSpinBox,
    QPlainTextEdit, QProgressBar, QSplitter, QCheckBox,
    QSizePolicy, QMessageBox,
    QFrame, QGridLayout, QAbstractItemView, QTabWidget,
    QScrollArea, QLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QRunnable, QThreadPool, QObject, QTimer
from PyQt6.QtGui import QColor, QImage, QKeySequence

from core.video_processor import RenderConfig, SubtitleStyle, FilePair, build_pairs
from core.worker import RenderWorker
from core.subtitle_model import SubtitleStylePreset
from core.srt_service import SrtService
from core.style_preset_service import StylePresetService
from core.subtitle_model import SubtitleEntry
from ui.subtitle_preview_widget import SubtitleStyleEditor
from ui.video_layer_config import VideoLayerConfigWidget
from ui.video_layout_preview import VideoLayoutPreview
from ui.collapsible_section import CollapsibleSection
from ui.flow_layout import FlowWidget, StackedField
from ui.spinbox_behavior import install_spinbox_behavior
from utils import settings as cfg
from utils.gpu_detect import check_ffmpeg, check_ffprobe
from core.license_manager import LicenseManager, LicenseStatus
from license.license_window import LicenseWindow, LicenseInfoDialog
from core.security import is_debugger_present, scan_suspicious_processes

if getattr(sys, 'frozen', False):
    EXPORT_PATH = Path(sys.executable).parent / "selections.json"
    DEBUG_LOG_PATH = Path(sys.executable).parent / "debug_ui.log"
else:
    EXPORT_PATH = Path(__file__).parent.parent / "selections.json"
    DEBUG_LOG_PATH = Path(__file__).parent.parent / "debug_ui.log"

CODECS = [
    ("H.265 HEVC — GPU (NVENC)", "hevc_nvenc"),
    ("H.264 AVC  — GPU (NVENC)", "h264_nvenc"),
    ("H.265 HEVC — CPU (libx265)", "libx265"),
    ("H.264 AVC  — CPU (libx264)", "libx264"),
]

from ui.media_widgets import (
    FolderPicker,
    FrameExtractSignals,
    FrameExtractTask,
    PairTable,
    _extract_video_frame,
)


class _BgProbeSignals(QObject):
    suspicious_proc = pyqtSignal(str)
    debugger = pyqtSignal()


class _BgProbeTask(QRunnable):
    """Off-thread anti-tamper scan (kept off the UI thread)."""

    def __init__(self, want_scan: bool = True):
        super().__init__()
        self.want_scan = want_scan
        self.signals = _BgProbeSignals()

    def run(self):
        if not self.want_scan:
            return
        try:
            if is_debugger_present():
                self.signals.debugger.emit()
                return
            proc = scan_suspicious_processes()
            if proc:
                self.signals.suspicious_proc.emit(proc)
        except Exception:
            pass


class _LicenseCheckSignals(QObject):
    result = pyqtSignal(object)  # LicenseInfo


class _LicenseCheckTask(QRunnable):
    """Off-thread periodic licence verification (does a network round-trip)."""

    def __init__(self):
        super().__init__()
        self.signals = _LicenseCheckSignals()

    def run(self):
        try:
            from core.license_manager import LicenseManager
            self.signals.result.emit(LicenseManager().check_license())
        except Exception:
            pass


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("EncoMie")
        
        # Thiết lập Icon cho cửa sổ ứng dụng
        from core.app_paths import get_app_icon
        app_icon = get_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self.setMinimumSize(1100, 650)
        self.resize(1280, 760)

        self._settings = cfg.load()
        self._pairs: list[FilePair] = []
        self._worker: RenderWorker | None = None
        self._presets: list[SubtitleStylePreset] = []
        self._active_preset: SubtitleStylePreset | None = None
        self._timing_undo: dict[str, list[SubtitleEntry]] = {}  # path → original entries
        self.logo_layers: list[VideoLayerConfigWidget] = []
        self.frame_pool = QThreadPool()
        self.frame_pool.setMaxThreadCount(2)
        self.running_extractions = set()

        # Dedicated pool for lightweight background probes (anti-tamper,
        # licence heartbeat) so none of them ever run on the UI thread.
        self._bg_pool = QThreadPool()
        self._bg_pool.setMaxThreadCount(2)

        # Debounce settings saving to avoid disk write stuttering during drags/edits
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_settings)

        self.license_manager = LicenseManager()

        # Background timer drives the periodic anti-tamper scan off the UI thread.
        self._bg_probe_timer = QTimer(self)
        self._bg_probe_timer.setInterval(5000)
        self._bg_probe_timer.timeout.connect(lambda: self._kick_bg_probe(scan=True))
        self._bg_probe_timer.start()

        # Background periodic licence heartbeat (network round-trip), ~12 min.
        # This only needs to catch a mid-session revocation/expiry reasonably
        # promptly; the signed token's own exp + offline grace cover everything
        # between beats. A short interval (it was 2 min) multiplied by every
        # running instance was burning the server's KV write budget.
        # Randomized +/-90s so several EncoMie instances on one machine don't
        # stay phase-locked; check_license() also coalesces near-simultaneous
        # beats across instances (see LicenseManager.HEARTBEAT_COALESCE_MS).
        self._license_timer = QTimer(self)
        self._license_timer.setInterval(12 * 60 * 1000 + random.randint(-90000, 90000))
        self._license_timer.timeout.connect(self._kick_license_check)
        self._license_timer.start()

        self._build_ui()
        install_spinbox_behavior(self)
        self._create_menu_bar()
        self._apply_saved_settings()
        self._log_debug("MainWindow initialized")
        # Defer everything that shells out so the window paints immediately.
        QTimer.singleShot(0, self._check_deps)
        QTimer.singleShot(500, self._check_license_on_startup)

    # ---- Background probes (never block the UI thread) ----

    def _kick_bg_probe(self, scan: bool = True):
        if not scan:
            return
        task = _BgProbeTask(want_scan=scan)
        task.signals.debugger.connect(self._on_security_violation_debugger)
        task.signals.suspicious_proc.connect(self._on_security_violation_proc)
        self._bg_pool.start(task)

    def _kick_license_check(self):
        task = _LicenseCheckTask()
        task.signals.result.connect(self._on_periodic_license_result)
        self._bg_pool.start(task)

    def _on_security_violation_debugger(self):
        self._bg_probe_timer.stop()
        QMessageBox.critical(
            self, "Cảnh Báo Bảo Mật",
            "Phát hiện công cụ Debugger đính kèm vào tiến trình ứng dụng.\nỨng dụng sẽ ngắt ngay lập tức!")
        sys.exit(0)

    def _on_security_violation_proc(self, proc: str):
        self._bg_probe_timer.stop()
        QMessageBox.critical(
            self, "Cảnh Báo Bảo Mật",
            f"Phát hiện công cụ can thiệp '{proc}' đang hoạt động trên hệ thống.\nỨng dụng sẽ ngắt ngay lập tức!")
        sys.exit(0)

    def _on_periodic_license_result(self, info):
        if info is None:
            return
        self._license_info = info
        self._apply_entitlements_to_ui(info)
        if info.status in [LicenseStatus.EXPIRED, LicenseStatus.REVOKED, LicenseStatus.SECURITY_VIOLATION]:
            QMessageBox.warning(
                self, "Bản Quyền Hết Hạn",
                "Thời hạn bản quyền ứng dụng EncoMie của bạn đã kết thúc.\nVui lòng kích hoạt key mới để tiếp tục sử dụng.")
            self._show_license_window(mandatory=True)

    def _guard_license_active(self) -> bool:
        """Pre-action security guard before running batch render or core tasks."""
        info = self.license_manager.check_license(force_refresh=True)
        self._license_info = info
        self._apply_entitlements_to_ui(info)
        if not info.is_valid:
            QMessageBox.warning(
                self,
                "Bản Quyền Hết Hạn / Không Hợp Lệ",
                "Không thể thực hiện tác vụ: Bản quyền ứng dụng đã hết hạn hoặc bị thu hồi.\nVui lòng gia hạn key mới."
            )
            self._show_license_window(mandatory=True)
            return False
        return True

    def _check_license_on_startup(self):
        info = self.license_manager.check_license()
        self._license_info = info
        self._apply_entitlements_to_ui(info)
        if info.status == LicenseStatus.SECURITY_VIOLATION:
            err_msg = info.raw_data.get("error", {}).get("message", "Cảnh báo bảo mật: Phát hiện công cụ can thiệp hoặc gian lận hệ thống.")
            QMessageBox.critical(
                self,
                "Cảnh Báo Bảo Mật (Security Alert)",
                f"Ứng dụng từ chối hoạt động:\n{err_msg}"
            )
            sys.exit(0)
        elif info.status == LicenseStatus.NOT_FOUND:
            self._show_license_window(mandatory=True)
        elif info.status in [LicenseStatus.EXPIRED, LicenseStatus.REVOKED, LicenseStatus.INVALID]:
            QMessageBox.warning(
                self,
                "Bản Quyền Hết Hạn / Không Hợp Lệ",
                "Bản quyền ứng dụng EncoMie của bạn đã hết hạn hoặc không hợp lệ.\nVui lòng kích hoạt key mới."
            )
            self._show_license_window(mandatory=True)

    def _create_menu_bar(self):
        menubar = self.menuBar()
        self.setMenuBar(menubar)
        menubar.setVisible(True)
        menubar.setStyleSheet("""
            QMenuBar {
                background-color: #ffffff;
                color: #0f172a;
                font-family: 'Segoe UI', 'Outfit', sans-serif;
                font-size: 13px;
                font-weight: 500;
                padding: 3px 6px;
                border-bottom: 1px solid #e2e8f0;
            }
            QMenuBar::item {
                background-color: transparent;
                color: #334155;
                padding: 6px 12px;
                border-radius: 6px;
                margin-right: 2px;
            }
            QMenuBar::item:selected {
                background-color: #f1f5f9;
                color: #2563eb;
                font-weight: 600;
            }
            QMenuBar::item:pressed {
                background-color: #e2e8f0;
                color: #1d4ed8;
            }
            QMenu {
                background-color: #ffffff;
                color: #1e293b;
                border: 1px solid #cbd5e1;
                padding: 6px;
                border-radius: 8px;
            }
            QMenu::item {
                padding: 7px 28px 7px 12px;
                border-radius: 6px;
                font-size: 13px;
                color: #334155;
            }
            QMenu::item:selected {
                background-color: #2563eb;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background-color: #e2e8f0;
                margin: 5px 8px;
            }
        """)

        # 1. File Menu
        file_menu = menubar.addMenu("File")
        
        open_act = file_menu.addAction("Mở Dự Án...")
        open_act.setShortcut(QKeySequence("Ctrl+O"))
        open_act.triggered.connect(self._load_project_file)

        save_act = file_menu.addAction("Lưu Dự Án")
        save_act.setShortcut(QKeySequence("Ctrl+S"))
        save_act.triggered.connect(self._save_project_file)

        file_menu.addSeparator()

        scan_act = file_menu.addAction("Quét Lại Video & SRT")
        scan_act.setShortcut(QKeySequence("F5"))
        scan_act.triggered.connect(self._scan_pairs)

        file_menu.addSeparator()

        exit_act = file_menu.addAction("Thoát")
        exit_act.setShortcut(QKeySequence("Alt+F4"))
        exit_act.triggered.connect(self.close)

        # 2. View Menu
        view_menu = menubar.addMenu("View")
        mode_sub_act = view_menu.addAction("Subtitle")
        mode_sub_act.setShortcut(QKeySequence("Ctrl+1"))
        mode_sub_act.triggered.connect(self._on_mode_sub_clicked)

        mode_vid_act = view_menu.addAction("Scale video")
        mode_vid_act.setShortcut(QKeySequence("Ctrl+2"))
        mode_vid_act.triggered.connect(self._on_mode_video_clicked)

        view_menu.addSeparator()
        clear_log_act = view_menu.addAction("Xóa Nhật Ký Render")
        clear_log_act.setShortcut(QKeySequence("Ctrl+L"))
        clear_log_act.triggered.connect(self.log_text.clear)

        # 3. Run Menu
        run_menu = menubar.addMenu("Run")
        start_run_act = run_menu.addAction("🚀 Bắt Đầu Render")
        start_run_act.setShortcut(QKeySequence("Ctrl+R"))
        start_run_act.triggered.connect(self._start_render)

        pause_run_act = run_menu.addAction("⏸ Tạm Dừng Render")
        pause_run_act.setShortcut(QKeySequence("Ctrl+P"))
        pause_run_act.triggered.connect(self._toggle_pause_render)

        stop_run_act = run_menu.addAction("⏹ Dừng Render")
        stop_run_act.setShortcut(QKeySequence("Ctrl+Shift+R"))
        stop_run_act.triggered.connect(self._stop_render)

        # 4. Help Menu
        help_menu = menubar.addMenu("Help")
        info_act = help_menu.addAction("🔑 Thông Tin License...")
        info_act.setShortcut(QKeySequence("Ctrl+I"))
        info_act.triggered.connect(self._show_license_info)

        act_act = help_menu.addAction("⚡ Kích Hoạt Key License...")
        act_act.setShortcut(QKeySequence("Ctrl+K"))
        act_act.triggered.connect(lambda: self._show_license_window(mandatory=False))

        help_menu.addSeparator()
        about_act = help_menu.addAction("ℹ️ Giới Thiệu EncoMie Pro...")
        about_act.setShortcut(QKeySequence("F1"))
        about_act.triggered.connect(self._show_about_dialog)

    def _show_about_dialog(self):
        QMessageBox.about(
            self,
            "Giới Thiệu EncoMie Pro",
            "<b>EncoMie Pro - Enterprise Commercial Video Suite</b><br>"
            "Phiên bản: <b>v1.5.1 Pro</b><br>"
            "Core Render: FFmpeg GPU Acceleration Engine<br>"
            "License: Cloudflare Global D1 Worker Engine 2026<br>"

        )

    def _show_license_window(self, mandatory=False):
        if mandatory:
            self.setDisabled(True)

        try:
            dlg = LicenseWindow(self.license_manager, self)
            res = dlg.exec()
            info = self.license_manager.check_license()

            if mandatory and (res != QDialog.DialogCode.Accepted or not info.is_valid):
                QMessageBox.critical(
                    self,
                    "Truy Cập Bị Từ Chối",
                    "Bản quyền ứng dụng của bạn chưa được kích hoạt hoặc đã hết hạn.\nỨng dụng sẽ tự động thoát."
                )
                sys.exit(0)
        finally:
            if mandatory and hasattr(self, "setEnabled"):
                self.setEnabled(True)

    def _show_license_info(self):
        info = self.license_manager.check_license()
        dlg = LicenseInfoDialog(self.license_manager, info, self)
        dlg.exec()

    def _log_debug(self, message: str):
        if not os.environ.get("ENCOMIE_DEBUG"):
            return
        line = f"[DEBUG] {message}"
        try:
            with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        if hasattr(self, "log_text"):
            try:
                self.log_text.appendPlainText(line)
            except Exception:
                pass

    def _apply_theme(self):
        try:
            import PyQt6.QtSvg  # noqa: F401
        except ImportError:
            pass

        from ui.theme import build_main_window_qss
        self.setStyleSheet(build_main_window_qss())

    def _build_ui(self):
        # Enable top MenuBar
        menu_bar = self.menuBar()
        menu_bar.setVisible(True)

        # Mode state buttons (internal state tracking)
        self.btn_tab_sub = QPushButton()
        self.btn_tab_sub.setCheckable(True)
        self.btn_tab_sub.setChecked(True)
        self.btn_tab_sub.clicked.connect(self._on_mode_sub_clicked)

        self.btn_tab_video = QPushButton()
        self.btn_tab_video.setCheckable(True)
        self.btn_tab_video.setChecked(False)
        self.btn_tab_video.clicked.connect(self._on_mode_video_clicked)

        central = QWidget()
        self.setCentralWidget(central)
        root_lay = QVBoxLayout(central)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # Instantiate style and layer controls first so panels can cross-reference them
        self.style_panel = SubtitleStyleEditor(self)
        self.style_panel.hide_preset_bar()
        # Remove _preview from style_panel layout and parent, but keep _ctrl inside it
        self.style_panel.layout().removeWidget(self.style_panel._preview)
        self.style_panel._preview.setParent(None)
        self.style_panel._preview.setVisible(True)

        self.layer_tab_widget = QTabWidget()
        self.layer_tab_widget.tabBar().setExpanding(True)
        self.layer_tab_widget.tabBar().setUsesScrollButtons(False)
        self.layer_tab_widget.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        self.layer_tab_widget.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #e5e5ea; border-radius: 4px; background: #ffffff; }"
            "QTabBar::tab { font-size: 10px; font-weight: bold; padding: 4px 10px; background: #f2f2f7; color: #636366; border: 1px solid #e5e5ea; }"
            "QTabBar::tab:selected { background: #ffffff; color: #007aff; border-bottom: 2px solid #007aff; }"
        )
        self.logo_layers = []
        for i in range(1, 6):
            ctrl = VideoLayerConfigWidget(i)
            ctrl.changed.connect(self._on_logo_settings_changed)
            ctrl.eyedropperRequested.connect(self._on_logo_eyedropper_requested)
            ctrl.cropModeToggled.connect(self._on_logo_crop_toggled)
            self.logo_layers.append(ctrl)
            self.layer_tab_widget.addTab(ctrl, f"L{i}")
            self.layer_tab_widget.setTabToolTip(i - 1, f"Layer {i}")
        self.layer_tab_widget.currentChanged.connect(self._on_logo_tab_changed)

        self.video_tab_widget = QTabWidget()
        self.video_tab_widget.tabBar().setExpanding(True)
        self.video_tab_widget.tabBar().setUsesScrollButtons(False)
        self.video_tab_widget.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        self.video_tab_widget.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #e2e8f0; border-radius: 8px; background: #ffffff; }"
            "QTabBar::tab { font-size: 11px; font-weight: 600; padding: 5px 12px; background: #f8fafc; color: #64748b; border: 1px solid #e2e8f0; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }"
            "QTabBar::tab:selected { background: #ffffff; color: #007aff; border-bottom: 2px solid #007aff; font-weight: 700; }"
        )
        self.video_layer_widgets = []
        for i in range(1, 6):
            widget = VideoLayerConfigWidget(i)
            widget.changed.connect(self._on_video_layer_changed)
            widget.cropModeToggled.connect(self._on_video_layer_crop_toggled)
            widget.eyedropperRequested.connect(self._on_eyedropper_requested)
            self.video_layer_widgets.append(widget)
            self.video_tab_widget.addTab(widget, f"L{i}")
            self.video_tab_widget.setTabToolTip(i - 1, f"Layer {i}")
        self.video_tab_widget.currentChanged.connect(self._on_video_tab_changed)

        # --- 3-panel horizontal splitter ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter = splitter
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet("QSplitter::handle { background-color: #e2e8f0; }")

        left   = self._build_left_panel()    # file selection
        middle = self._build_middle_panel()  # video player
        right  = self._build_right_panel()   # inspector tabs & render log
        left.setMinimumWidth(300)
        middle.setMinimumWidth(320)
        right.setMinimumWidth(360)

        splitter.addWidget(left)
        splitter.addWidget(middle)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([300, 618, 360])

        root_lay.addWidget(splitter, 1)

        self._apply_theme()
        self.statusBar().showMessage("Sẵn sàng")

    # ---- Left panel ----

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet("background-color: #ffffff; border-right: 1px solid #e5e5ea;")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(8)

        header_lay = QHBoxLayout()
        header_lbl = QLabel("TỆP DỰ ÁN")
        header_lbl.setToolTip("Project Media")
        header_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #1c1c1e;")
        header_lay.addWidget(header_lbl)
        header_lay.addStretch()
        
        self.btn_refresh = QPushButton("⚡  Quét cặp")
        self.btn_refresh.setStyleSheet("font-size: 10px; padding: 3px 8px; background-color: #f2f2f7; border: 1px solid #d1d1d6; color: #1c1c1e;")
        self.btn_refresh.clicked.connect(self._scan_pairs)
        header_lay.addWidget(self.btn_refresh)
        lay.addLayout(header_lay)

        # 1. Edit Sub Container
        self.left_sub_container = QWidget()
        sub_lay = QVBoxLayout(self.left_sub_container)
        sub_lay.setContentsMargins(0, 0, 0, 0)
        sub_lay.setSpacing(6)

        self.pick_bg = FolderPicker("📁 Nền:", "Chọn file video nền")
        self.pick_audio = FolderPicker("🎵 Media:", "Chọn file video/audio nguồn")
        self.pick_srt = FolderPicker("✍️ Phụ đề:", "Chọn thư mục chứa file .srt")

        self.pick_bg.set_mode("files")
        self.pick_audio.set_mode("files")
        self.pick_srt.set_mode("files")
        self.pick_bg.set_file_dialog(
            "Chọn file video nền",
            "Video files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v);;All files (*.*)"
        )
        self.pick_srt.set_file_dialog(
            "Chọn file phụ đề",
            "Subtitle files (*.srt);;All files (*.*)"
        )
        self.pick_bg.btn.setText("Chọn")
        self.pick_audio.btn.setText("Chọn")
        self.pick_srt.btn.setText("Chọn")

        self.pick_bg.set_callback(self._on_file_selection_change)
        self.pick_audio.set_callback(self._on_file_selection_change)
        self.pick_srt.set_callback(self._on_file_selection_change)

        for w in [self.pick_bg, self.pick_audio, self.pick_srt]:
            sub_lay.addWidget(w)

        self.pair_table = PairTable()
        self.pair_table.itemSelectionChanged.connect(self._on_pair_selection_changed)
        self.pair_table.itemChanged.connect(self._on_table_item_changed)
        sub_lay.addWidget(self.pair_table, 1)

        # Full-width summary label above action buttons
        self.lbl_pair_summary = QLabel("Chưa quét")
        self.lbl_pair_summary.setStyleSheet("font-size: 11px; font-weight: 500; color: #475569; padding: 2px 0;")
        self.lbl_pair_summary.setWordWrap(True)
        sub_lay.addWidget(self.lbl_pair_summary)

        pair_btn_lay = QHBoxLayout()
        pair_btn_lay.setContentsMargins(0, 0, 0, 0)
        pair_btn_lay.setSpacing(6)
        self.btn_pair_select_all = QPushButton("Chọn hết")
        self.btn_pair_select_all.setToolTip("Chọn tất cả")
        self.btn_pair_select_all.setStyleSheet("font-size: 11px; padding: 3px 8px;")
        self.btn_pair_select_all.clicked.connect(self._pair_select_all)
        self.btn_pair_deselect_all = QPushButton("Bỏ chọn")
        self.btn_pair_deselect_all.setToolTip("Bỏ chọn tất cả")
        self.btn_pair_deselect_all.setStyleSheet("font-size: 11px; padding: 3px 8px;")
        self.btn_pair_deselect_all.clicked.connect(self._pair_deselect_all)
        pair_btn_lay.addWidget(self.btn_pair_select_all)
        pair_btn_lay.addWidget(self.btn_pair_deselect_all)
        pair_btn_lay.addStretch(1)
        sub_lay.addLayout(pair_btn_lay)

        lay.addWidget(self.left_sub_container, 1)

        # 2. Edit Video Container
        self.left_video_container = QWidget()
        vid_lay = QVBoxLayout(self.left_video_container)
        vid_lay.setContentsMargins(0, 0, 0, 0)
        vid_lay.setSpacing(6)

        self.pick_vid_src = FolderPicker("🎥 Nguồn:", "Chọn thư mục video nguồn")
        self.pick_vid_bg = FolderPicker("📁 Nền:", "Chọn file video nền (tùy chọn)")

        self.pick_vid_bg.set_mode("files")
        self.pick_vid_bg.set_file_dialog(
            "Chọn file video nền",
            "Video files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v);;All files (*.*)"
        )
        self.pick_vid_bg.btn.setText("Chọn")
        
        self.pick_vid_src.set_callback(self._on_video_selection_change)
        self.pick_vid_bg.set_callback(self._on_video_selection_change)

        for w in [self.pick_vid_src, self.pick_vid_bg]:
            vid_lay.addWidget(w)

        self.vid_batch_table = QTableWidget(0, 4)
        self.vid_batch_table.setHorizontalHeaderLabels(["#", "VIDEO", "ĐỘ PHÂN GIẢI", "TRẠNG THÁI"])
        for column, tip in enumerate(("Số thứ tự", "Tên video nguồn", "Độ phân giải", "Trạng thái")):
            self.vid_batch_table.horizontalHeaderItem(column).setToolTip(tip)
        self.vid_batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vid_batch_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.vid_batch_table.setAlternatingRowColors(True)
        self.vid_batch_table.verticalHeader().setVisible(False)
        hdr = self.vid_batch_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hdr.setStretchLastSection(False)
        hdr.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.vid_batch_table.setColumnWidth(0, 40)
        self.vid_batch_table.setColumnWidth(3, 100)
        # Stylesheet is managed globally
        self.vid_batch_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.vid_batch_table.itemSelectionChanged.connect(self._on_video_batch_selection_changed)
        self.vid_batch_table.itemChanged.connect(self._on_table_item_changed)
        vid_lay.addWidget(self.vid_batch_table, 1)

        # Full-width video summary label above action buttons
        self.lbl_vid_summary = QLabel("Chưa quét")
        self.lbl_vid_summary.setStyleSheet("font-size: 11px; font-weight: 500; color: #475569; padding: 2px 0;")
        self.lbl_vid_summary.setWordWrap(True)
        vid_lay.addWidget(self.lbl_vid_summary)

        vid_btn_lay = QHBoxLayout()
        vid_btn_lay.setContentsMargins(0, 0, 0, 0)
        vid_btn_lay.setSpacing(6)
        self.btn_vid_select_all = QPushButton("Chọn hết")
        self.btn_vid_select_all.setToolTip("Chọn tất cả")
        self.btn_vid_select_all.setStyleSheet("font-size: 11px; padding: 3px 8px;")
        self.btn_vid_select_all.clicked.connect(self._vid_select_all)
        self.btn_vid_deselect_all = QPushButton("Bỏ chọn")
        self.btn_vid_deselect_all.setToolTip("Bỏ chọn tất cả")
        self.btn_vid_deselect_all.setStyleSheet("font-size: 11px; padding: 3px 8px;")
        self.btn_vid_deselect_all.clicked.connect(self._vid_deselect_all)
        vid_btn_lay.addWidget(self.btn_vid_select_all)
        vid_btn_lay.addWidget(self.btn_vid_deselect_all)
        vid_btn_lay.addStretch(1)
        vid_lay.addLayout(vid_btn_lay)

        lay.addWidget(self.left_video_container, 1)
        self.left_video_container.setVisible(False)

        return panel

    def _build_middle_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet("background-color: #f8fafc;")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # Viewport Header Bar (Matching Light Theme UI Mockup)
        v_header = QWidget()
        v_header.setFixedHeight(36)
        v_header.setStyleSheet("background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;")
        vh_lay = QHBoxLayout(v_header)
        vh_lay.setContentsMargins(12, 4, 12, 4)
        vh_lay.setSpacing(8)

        vh_title = QLabel("🖥  XEM TRƯỚC")
        vh_title.setToolTip("XEM TRƯỚC (LIVE MONITOR)")
        vh_title.setStyleSheet("font-size: 11px; font-weight: 700; color: #0f172a;")
        
        self.lbl_viewport_res = QLabel("1280x720")
        self.lbl_viewport_res.setToolTip("1280x720 (16:9 HD)")
        self.lbl_viewport_res.setStyleSheet("font-size: 10px; font-weight: 500; color: #64748b;")

        vh_badge = QLabel("● Live")
        vh_badge.setToolTip("Live Sync 1:1")
        vh_badge.setStyleSheet(
            "background-color: #ecfdf5; color: #059669; border: 1px solid #a7f3d0; "
            "border-radius: 6px; padding: 2px 6px; font-size: 9px; font-weight: 600;"
        )

        vh_lay.addWidget(vh_title)
        vh_lay.addWidget(self.lbl_viewport_res)
        vh_lay.addStretch(1)
        vh_lay.addWidget(vh_badge)

        lay.addWidget(v_header)

        # Viewer Stacked Area
        self.viewer_stack = QWidget()
        viewer_lay = QVBoxLayout(self.viewer_stack)
        viewer_lay.setContentsMargins(0, 0, 0, 0)
        viewer_lay.setSpacing(0)

        # 1. Edit Sub Viewer (Preview Widget)
        self.middle_sub_container = QWidget()
        sub_view_lay = QVBoxLayout(self.middle_sub_container)
        sub_view_lay.setContentsMargins(0, 0, 0, 0)
        self.preview_widget = self.style_panel._preview
        self.preview_widget.colorPicked.connect(self._on_logo_preview_color_picked)
        self.preview_widget.layerSelected.connect(self._on_logo_preview_layer_selected)
        self.preview_widget.layerMoved.connect(self._on_logo_preview_layer_moved)
        self.preview_widget.layerResized.connect(self._on_logo_preview_layer_resized)
        self.preview_widget.layerCropped.connect(self._on_logo_preview_layer_cropped)
        self.preview_widget.bgZoomChanged.connect(self._on_preview_bg_zoom_changed)
        self.preview_widget.setMinimumHeight(240)
        self.preview_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.preview_widget.clicked.connect(self._on_refresh_preview_frame)
        self.preview_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_widget.setToolTip("Click để làm mới khung hình xem trước")
        self.preview_widget.setVisible(True)
        sub_view_lay.addWidget(self.preview_widget)
        viewer_lay.addWidget(self.middle_sub_container)

        # 2. Edit Video Viewer (Video Layout Preview)
        self.middle_video_container = QWidget()
        vid_view_lay = QVBoxLayout(self.middle_video_container)
        vid_view_lay.setContentsMargins(0, 0, 0, 0)
        self.video_layout_preview = VideoLayoutPreview()
        self.video_layout_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.video_layout_preview.layerSelected.connect(self._on_preview_layer_selected)
        self.video_layout_preview.layerMoved.connect(self._on_preview_layer_moved)
        self.video_layout_preview.layerResized.connect(self._on_preview_layer_resized)
        self.video_layout_preview.layerCropped.connect(self._on_preview_layer_cropped)
        self.video_layout_preview.colorPicked.connect(self._on_preview_color_picked)
        self.video_layout_preview.bgZoomChanged.connect(self._on_preview_bg_zoom_changed)
        vid_view_lay.addWidget(self.video_layout_preview)
        viewer_lay.addWidget(self.middle_video_container)
        self.middle_video_container.setVisible(False)

        lay.addWidget(self.viewer_stack, 1)

        return panel

    def _on_style_changed(self, style: SubtitleStylePreset):
        """Sync style changes from style_panel to preview_widget."""
        if hasattr(self, "preview_widget"):
            self.preview_widget.set_style(style)
        self._active_preset = None

    def _on_resolution_changed(self):
        """Sync resolution changes to video_layout_preview, preview_widget, and top Live Monitor label."""
        full_text = self.cmb_resolution.currentText()
        if hasattr(self, "lbl_viewport_res"):
            self.lbl_viewport_res.setText(full_text.split(" ")[0])
            self.lbl_viewport_res.setToolTip(full_text)

        res_val = full_text.split(" ")[0]
        if "x" in res_val:
            try:
                w, h = map(int, res_val.split("x"))
                if hasattr(self, "video_layout_preview"):
                    self.video_layout_preview.set_target_resolution(w, h)
                if hasattr(self, "preview_widget"):
                    if hasattr(self.preview_widget, "set_target_resolution"):
                        self.preview_widget.set_target_resolution(w, h)
            except Exception as e:
                print(f"[DEBUG] Error setting target resolution on previews: {e}")

    def _on_bg_zoom_changed(self, val: float):
        if hasattr(self, "video_layout_preview"):
            self.video_layout_preview.set_bg_zoom(val)
        if hasattr(self, "preview_widget"):
            if hasattr(self.preview_widget, "set_bg_zoom"):
                self.preview_widget.set_bg_zoom(val)
        if hasattr(self, "_save_timer"):
            self._save_timer.start(1000)

    def _on_preview_bg_zoom_changed(self, val: float):
        if hasattr(self, "spn_bg_zoom"):
            self.spn_bg_zoom.blockSignals(True)
            self.spn_bg_zoom.setValue(val)
            self.spn_bg_zoom.blockSignals(False)
            self._on_bg_zoom_changed(val)

    def _on_logo_settings_changed(self):
        self._update_logo_preview_frames()

    def _apply_entitlements_to_ui(self, info):
        try:
            from core.entitlements import Entitlements
            locked = not Entitlements.from_license(info).color_grade
            for ctrl in list(getattr(self, "logo_layers", [])) + list(getattr(self, "video_layer_widgets", [])):
                if hasattr(ctrl, "set_color_locked"):
                    ctrl.set_color_locked(locked)
        except Exception:
            pass

    def _update_logo_preview_frames(self):
        if not hasattr(self, "preview_widget") or not hasattr(self, "logo_layers") or not self.logo_layers:
            return
            
        configs = []
        for idx, ctrl in enumerate(self.logo_layers):
            cfg_obj = ctrl.get_config()
            configs.append(cfg_obj)
            active = cfg_obj.enabled and bool(cfg_obj.path)
            self.layer_tab_widget.setTabText(idx, f"L{idx + 1}")
            self.layer_tab_widget.setTabToolTip(
                idx, f"Layer {idx + 1}{' (đang bật)' if active else ''}"
            )
            
            # Extract video/image frame for logo preview
            layer_img = None
            if cfg_obj.enabled:
                src_idx = ctrl.cmb_source_type.currentIndex()
                path_to_load = ""
                if src_idx == 0:  # Video nền (Background video)
                    bg_files = self.pick_vid_bg.selected_files()
                    if bg_files:
                        path_to_load = bg_files[0]
                elif src_idx == 1:  # Theo danh sách chạy (Video nguồn)
                    selected_ranges = self.vid_batch_table.selectedRanges()
                    if selected_ranges:
                        row = selected_ranges[0].topRow()
                        if 0 <= row < len(self._pairs):
                            path_to_load = self._pairs[row].audio_path
                else:  # File cố định (Static file)
                    path_to_load = ctrl.edit_path.text().strip()
                
                if path_to_load and os.path.exists(path_to_load):
                    layer_img = self._get_logo_preview_frame(path_to_load)
            
            if layer_img:
                self.preview_widget._logo_images[cfg_obj.path] = layer_img
            ctrl.set_curve_histogram(layer_img)

        self.preview_widget.set_logo_layers(configs)
        self._save_timer.start(1000)

    def _get_logo_preview_frame(self, path):
        if not path or not os.path.exists(path):
            return None
        if not hasattr(self, "_video_frame_cache"):
            self._video_frame_cache = {}
        if path in self._video_frame_cache:
            return self._video_frame_cache[path]
            
        lower_path = path.lower()
        if any(lower_path.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".bmp", ".webp"]):
            img = QImage(path)
            if not img.isNull():
                self._add_frame_to_cache(path, img)
                return self._video_frame_cache[path]
                
        # Asynchronous extraction for videos to prevent UI freezing
        if path in self.running_extractions:
            return None
            
        self.running_extractions.add(path)
        task = FrameExtractTask(path)
        task.signals.loaded.connect(self._on_logo_frame_loaded)
        self.frame_pool.start(task)
        return None

    def _on_logo_frame_loaded(self, path: str, image: QImage):
        if path in self.running_extractions:
            self.running_extractions.remove(path)
        if image and not image.isNull():
            self._add_frame_to_cache(path, image)
            self._update_logo_preview_frames()

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(360)
        panel.setStyleSheet("background-color: #ffffff; border-left: 1px solid #e5e5ea;")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # --- Flat Segmented Control Inspector Tab Bar ---
        tab_selector = QWidget()
        tab_selector.setFixedHeight(36)
        tab_selector.setStyleSheet(
            "background-color: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 8px;"
        )
        ts_lay = QHBoxLayout(tab_selector)
        ts_lay.setContentsMargins(3, 3, 3, 3)
        ts_lay.setSpacing(3)

        self.inspector_tab_buttons = []
        tab_specs = [
            ("Phụ đề", "Chỉnh kiểu phụ đề"),
            ("Lớp", "Cấu hình 5 lớp"),
            ("Xuất", "Xuất video"),
        ]
        for i, (text, tooltip) in enumerate(tab_specs):
            btn = QPushButton(text)
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { background: transparent; color: #64748b; border: none; font-size: 11px; font-weight: 600; border-radius: 6px; }"
                "QPushButton:hover { color: #0f172a; background: rgba(255, 255, 255, 0.5); }"
                "QPushButton:checked { color: #007aff; background-color: #ffffff; border: 1px solid #cbd5e1; font-weight: 700; }"
            )
            if i == 0:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, idx=i: self._on_inspector_tab_clicked(idx))
            self.inspector_tab_buttons.append(btn)
            ts_lay.addWidget(btn)

        lay.addWidget(tab_selector)

        # --- Inspector QTabWidget ---
        self.inspector_tab_widget = QTabWidget()
        self.inspector_tab_widget.tabBar().setVisible(False) # Hide original tabbar
        self.inspector_tab_widget.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")

        # Tab 0: Subtitle & Style
        tab_sub = QWidget()
        tab_sub_lay = QVBoxLayout(tab_sub)
        tab_sub_lay.setContentsMargins(0, 4, 0, 0)
        tab_sub_lay.setSpacing(8)

        # Preset bar (Moved from middle panel)
        preset_bar = QWidget()
        preset_bar.setFixedHeight(32)
        preset_bar.setStyleSheet("background: #ffffff; border-radius: 4px; border: 1px solid #e5e5ea;")
        pst_lay = QHBoxLayout(preset_bar)
        pst_lay.setContentsMargins(8, 0, 8, 0)
        pst_lay.setSpacing(6)

        title = QLabel("Mẫu:")
        title.setToolTip("Mẫu kiểu phụ đề")
        title.setStyleSheet("color: #636366; font-size: 10px; font-weight: bold;")
        pst_lay.addWidget(title)

        self.cmb_preset = QComboBox()
        self.cmb_preset.setMinimumWidth(84)
        self.cmb_preset.setStyleSheet(
            "QComboBox { background: #ffffff; color: #1c1c1e; border: 1px solid #e5e5ea; "
            "border-radius: 4px; padding: 0px 8px; font-size: 11px; height: 24px; }"
        )
        self.cmb_preset.currentIndexChanged.connect(self._on_preset_changed)
        pst_lay.addWidget(self.cmb_preset, 1)

        for icon, tip, handler in [
            ("💾", "Lưu mẫu", self._on_save_preset),
            ("🗑", "Xóa mẫu", self._on_delete_preset_inline),
            ("↺", "Khôi phục mặc định", self._on_reset_defaults_inline),
        ]:
            btn = QPushButton(icon)
            btn.setFixedSize(26, 22)
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)
            btn.setStyleSheet(
                "QPushButton { background: #ffffff; color: #1c1c1e; border: 1px solid #e5e5ea; "
                "border-radius: 4px; font-size: 11px; padding: 0; }"
                "QPushButton:hover { background: #007aff; border-color: #007aff; color: white; }"
            )
            btn.clicked.connect(handler)
            pst_lay.addWidget(btn)

        tab_sub_lay.addWidget(preset_bar)

        # Configure and connect pre-instantiated Subtitle Style Editor
        # self.style_panel._preview.setVisible(False) # Keep it visible since it's moved to middle panel
        self.style_panel.style_changed.connect(self._on_style_changed)
        tab_sub_lay.addWidget(self.style_panel, 1)

        # Timing Tools (Moved from right panel)
        grp_timing = QGroupBox("Công cụ thời gian")
        grp_timing.setStyleSheet(
            "QGroupBox { font-size: 11px; font-weight: 600; color: #374151; }"
        )
        timing_lay = QHBoxLayout(grp_timing)
        timing_lay.setContentsMargins(8, 8, 8, 8)
        timing_lay.setSpacing(6)

        self.btn_first_to_zero = QPushButton("⏮  Dời về 0s")
        self.btn_first_to_zero.setAccessibleName("Dời phụ đề đầu tiên về 0 giây")
        self.btn_first_to_zero.setStyleSheet(
            "QPushButton { min-height: 30px; font-size: 11px; font-weight: 600; color: white; "
            "background: #007aff; border: 1px solid #007aff; border-radius: 5px; padding: 0 10px; }"
            "QPushButton:hover { background: #0066d6; }"
            "QPushButton:focus { border: 2px solid #60a5fa; }"
            "QPushButton:disabled { background: #a8c9ee; border-color: #a8c9ee; color: #f8fafc; }"
        )
        self.btn_first_to_zero.setToolTip(
            "Dời toàn bộ thời gian để phụ đề đầu tiên bắt đầu tại 0 giây."
        )
        self.btn_first_to_zero.clicked.connect(self._on_first_sub_to_zero)
        timing_lay.addWidget(self.btn_first_to_zero)

        self.btn_undo_timing = QPushButton("↩  Hoàn tác")
        self.btn_undo_timing.setAccessibleName("Hoàn tác thay đổi thời gian")
        self.btn_undo_timing.setStyleSheet(
            "QPushButton { min-height: 30px; font-size: 11px; color: #334155; background: transparent; "
            "border: 1px solid #94a3b8; border-radius: 5px; padding: 0 10px; }"
            "QPushButton:hover { background: #f1f5f9; border-color: #007aff; }"
            "QPushButton:focus { border: 2px solid #007aff; }"
            "QPushButton:disabled { color: #9ca3af; border-color: #d1d5db; background: #f8fafc; }"
        )
        self.btn_undo_timing.setToolTip("Hoàn tác lần thay đổi thời gian gần nhất.")
        self.btn_undo_timing.setEnabled(False)
        self.btn_undo_timing.clicked.connect(self._on_undo_timing)
        timing_lay.addWidget(self.btn_undo_timing)

        tab_sub_lay.addWidget(grp_timing)
        self.inspector_tab_widget.addTab(tab_sub, "Phụ đề")

        # Tab 1: Layer Configuration
        tab_layer = QWidget()
        tab_layer_lay = QVBoxLayout(tab_layer)
        tab_layer_lay.setContentsMargins(0, 4, 0, 0)
        tab_layer_lay.setSpacing(8)

        # Add pre-instantiated layer tab widgets
        tab_layer_lay.addWidget(self.layer_tab_widget)
        tab_layer_lay.addWidget(self.video_tab_widget)
        
        # Initially, show image layers, hide video layers
        self.layer_tab_widget.setVisible(True)
        self.video_tab_widget.setVisible(False)

        self.inspector_tab_widget.addTab(tab_layer, "Layer")

        # Tab 2: Export & System Settings (Scrollable)
        tab_export_scroll = QScrollArea()
        tab_export_scroll.setWidgetResizable(True)
        tab_export_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tab_export_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tab_export_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        tab_export_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 6px; background: #f8fafc; border-radius: 3px; }"
            "QScrollBar::handle:vertical { background: #cbd5e1; border-radius: 3px; min-height: 20px; }"
            "QScrollBar::handle:vertical:hover { background: #94a3b8; }"
        )

        tab_export = QWidget()
        tab_export.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        tab_export_lay = QVBoxLayout(tab_export)
        tab_export_lay.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        tab_export_lay.setContentsMargins(0, 2, 0, 2)
        tab_export_lay.setSpacing(6)

        # 1. Thư mục xuất video
        grp_output = QGroupBox("📤  Thư mục xuất video", tab_export)
        grp_output.setStyleSheet("QGroupBox { font-size: 11px; font-weight: bold; }")
        out_lay = QVBoxLayout(grp_output)
        out_lay.setContentsMargins(6, 6, 6, 6)
        self.pick_output = FolderPicker("Xuất:", "Chọn thư mục xuất video", parent=grp_output)
        self.pick_output.btn.setText("Chọn")
        out_lay.addWidget(self.pick_output)
        tab_export_lay.addWidget(grp_output)

        # 2. Thông số Render
        grp_render = QGroupBox("⚙️  Thông số Render", tab_export)
        grp_render.setStyleSheet("QGroupBox { font-size: 11px; font-weight: bold; }")
        r_lay = QVBoxLayout(grp_render)
        r_lay.setSpacing(4)
        r_lay.setContentsMargins(0, 6, 0, 6)

        # Target Resolution Dropdown
        res_lbl = QLabel("Độ phân giải:", grp_render)
        res_lbl.setStyleSheet("font-size: 11px; color: #8e8e93;")
        r_lay.addWidget(res_lbl)
        
        self.cmb_resolution = QComboBox(grp_render)
        self.cmb_resolution.addItem("1280x720 (HD - 16:9)")
        self.cmb_resolution.addItem("1920x1080 (FullHD - 16:9)")
        self.cmb_resolution.addItem("720x1280 (Dọc - TikTok)")
        self.cmb_resolution.addItem("1080x1920 (Dọc FullHD)")
        self.cmb_resolution.currentIndexChanged.connect(self._on_resolution_changed)
        r_lay.addWidget(self.cmb_resolution)

        codec_lbl = QLabel("Codec xuất:", grp_render)
        codec_lbl.setStyleSheet("font-size: 11px; color: #636366;")
        r_lay.addWidget(codec_lbl)

        self.cmb_codec = QComboBox(grp_render)
        for label, _ in CODECS:
            self.cmb_codec.addItem(label)
        r_lay.addWidget(self.cmb_codec)

        # Group FPS & Concurrent in one compact 2-column row
        perf_row = QHBoxLayout()
        perf_row.setSpacing(8)

        fps_col = QVBoxLayout()
        fps_col.setSpacing(2)
        fps_lbl = QLabel("Khung hình (FPS):", grp_render)
        fps_lbl.setWordWrap(True)
        fps_lbl.setStyleSheet("font-size: 11px; color: #636366;")
        fps_col.addWidget(fps_lbl)

        self.cmb_fps = QComboBox(grp_render)
        self.cmb_fps.addItem("60 FPS", "60")
        self.cmb_fps.addItem("50 FPS", "50")
        self.cmb_fps.addItem("30 FPS", "30")
        self.cmb_fps.addItem("25 FPS", "25")
        self.cmb_fps.addItem("24 FPS", "24")
        self.cmb_fps.addItem("23.976 FPS", "24000/1001")
        self.cmb_fps.setCurrentIndex(2) # Default to 30 FPS
        fps_col.addWidget(self.cmb_fps)
        perf_row.addLayout(fps_col, 1)

        conc_col = QVBoxLayout()
        conc_col.setSpacing(2)
        concurrent_lbl = QLabel("Render song song:", grp_render)
        concurrent_lbl.setWordWrap(True)
        concurrent_lbl.setStyleSheet("font-size: 11px; color: #636366;")
        conc_col.addWidget(concurrent_lbl)

        self.spn_concurrent = QSpinBox(grp_render)
        self.spn_concurrent.setRange(1, 8)
        self.spn_concurrent.setProperty("spinDebugName", "export.concurrent")
        self.spn_concurrent.setValue(2)
        self.spn_concurrent.setSuffix(" luồng")
        conc_col.addWidget(self.spn_concurrent)
        perf_row.addLayout(conc_col, 1)

        r_lay.addLayout(perf_row)

        speed_lbl = QLabel("Tốc độ chậm của video nền:", grp_render)
        speed_lbl.setStyleSheet("font-size: 11px; color: #8e8e93;")
        r_lay.addWidget(speed_lbl)

        speed_row = QHBoxLayout()
        speed_row.setSpacing(6)

        min_lbl = QLabel("Min:", grp_render)
        min_lbl.setStyleSheet("font-size: 11px; color: #8e8e93;")
        speed_row.addWidget(min_lbl)

        self.spn_slow_min = QDoubleSpinBox(grp_render)
        self.spn_slow_min.setRange(10, 100)
        self.spn_slow_min.setProperty("spinDebugName", "export.slow_min")
        self.spn_slow_min.setDecimals(0)
        self.spn_slow_min.setValue(35.0)
        self.spn_slow_min.setSingleStep(1.0)
        self.spn_slow_min.setSuffix(" %")
        speed_row.addWidget(self.spn_slow_min, 1)

        max_lbl = QLabel("Max:", grp_render)
        max_lbl.setStyleSheet("font-size: 11px; color: #8e8e93;")
        speed_row.addWidget(max_lbl)

        self.spn_slow_max = QDoubleSpinBox(grp_render)
        self.spn_slow_max.setRange(10, 100)
        self.spn_slow_max.setProperty("spinDebugName", "export.slow_max")
        self.spn_slow_max.setDecimals(0)
        self.spn_slow_max.setValue(45.0)
        self.spn_slow_max.setSingleStep(1.0)
        self.spn_slow_max.setSuffix(" %")
        speed_row.addWidget(self.spn_slow_max, 1)

        r_lay.addLayout(speed_row)

        # Thu phóng video nền (gọn, không nút 100%, không mô tả)
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(6)
        zoom_lbl = QLabel("Thu phóng nền:", grp_render)
        zoom_lbl.setStyleSheet("font-size: 11px; color: #8e8e93;")
        zoom_lbl.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        zoom_row.addWidget(zoom_lbl)

        self.spn_bg_zoom = QDoubleSpinBox(grp_render)
        self.spn_bg_zoom.setRange(20, 300)
        self.spn_bg_zoom.setProperty("spinDebugName", "export.bg_zoom")
        self.spn_bg_zoom.setDecimals(0)
        self.spn_bg_zoom.setValue(100.0)
        self.spn_bg_zoom.setSingleStep(5.0)
        self.spn_bg_zoom.setSuffix(" %")
        self.spn_bg_zoom.setToolTip("Tỷ lệ thu phóng video nền (100% = vừa khung, >100% = phóng to. Giữ Ctrl + cuộn chuột trên Preview để thu phóng)")
        self.spn_bg_zoom.valueChanged.connect(self._on_bg_zoom_changed)
        zoom_row.addWidget(self.spn_bg_zoom, 1)

        r_lay.addLayout(zoom_row)
        perf_flow = FlowWidget()
        perf_flow.add_field("FPS:", self.cmb_fps, input_width=78)
        perf_flow.add_field("Luồng:", self.spn_concurrent, input_width=78)
        r_lay.addWidget(perf_flow)

        bg_flow = FlowWidget()
        bg_flow.add_field("Chậm min:", self.spn_slow_min, input_width=78)
        bg_flow.add_field("Chậm max:", self.spn_slow_max, input_width=78)
        bg_flow.add_field("Thu phóng:", self.spn_bg_zoom, input_width=78)
        r_lay.addWidget(bg_flow)
        for label in (fps_lbl, concurrent_lbl, speed_lbl, min_lbl, max_lbl, zoom_lbl):
            label.hide()
        tab_export_lay.addWidget(grp_render)

        # 3. Render controls
        grp_ctrl = QGroupBox("Tiến trình", tab_export)
        grp_ctrl.setStyleSheet("QGroupBox { font-size: 11px; font-weight: bold; }")
        ctrl_lay = QVBoxLayout(grp_ctrl)
        ctrl_lay.setSpacing(4)
        ctrl_lay.setContentsMargins(6, 6, 6, 6)

        self.progress_bar = QProgressBar(grp_ctrl)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #d1d1d6; border-radius: 4px; "
            "background: #e5e5ea; text-align: center; font-size: 10px; color: #1c1c1e; }"
            "QProgressBar::chunk { background: #007aff; border-radius: 3px; }"
        )
        ctrl_lay.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Sẵn sàng", grp_ctrl)
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size: 11px; color: #636366;")
        ctrl_lay.addWidget(self.lbl_status)

        self.btn_render = QPushButton("Xuất video", grp_ctrl)
        self.btn_render.setToolTip("Bắt đầu xuất video")
        self.btn_render.setFixedHeight(30)
        self.btn_render.setStyleSheet(
            "QPushButton { background: #007aff; color: white; font-size: 11px; "
            "font-weight: bold; border-radius: 5px; border: none; }"
            "QPushButton:hover { background: #0062cc; }"
            "QPushButton:disabled { background: #e5e5ea; color: #a1a1aa; }"
        )
        self.btn_render.clicked.connect(self._start_render)
        ctrl_lay.addWidget(self.btn_render)

        btn_row = QGridLayout()
        btn_row.setHorizontalSpacing(6)
        btn_row.setVerticalSpacing(4)

        self.btn_pause = QPushButton("Tạm dừng", grp_ctrl)
        self.btn_pause.setToolTip("Tạm dừng hoặc tiếp tục xuất video")
        self.btn_pause.setFixedHeight(24)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet(
            "QPushButton { background: #fef3c7; color: #d97706; font-size: 10.5px; "
            "font-weight: bold; border-radius: 4px; border: 1px solid #fde68a; }"
            "QPushButton:hover { background: #fde68a; }"
            "QPushButton:disabled { background: #f8fafc; color: #cbd5e1; border-color: #e2e8f0; }"
        )
        self.btn_pause.clicked.connect(self._toggle_pause_render)
        btn_row.addWidget(self.btn_pause, 0, 0)

        self.btn_stop = QPushButton("Hủy render", grp_ctrl)
        self.btn_stop.setToolTip("Hủy tiến trình xuất video đang chạy")
        self.btn_stop.setFixedHeight(24)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "QPushButton { background: #fee2e2; color: #dc2626; font-size: 10.5px; "
            "font-weight: bold; border-radius: 4px; border: 1px solid #fca5a5; }"
            "QPushButton:hover { background: #fca5a5; }"
            "QPushButton:disabled { background: #f8fafc; color: #cbd5e1; border-color: #e2e8f0; }"
        )
        self.btn_stop.clicked.connect(self._stop_render)
        btn_row.addWidget(self.btn_stop, 0, 1)

        self.btn_export = QPushButton("Xuất JSON", grp_ctrl)
        self.btn_export.setToolTip("Xuất cấu hình dự án ra JSON")
        self.btn_export.setFixedHeight(24)
        self.btn_export.setStyleSheet(
            "QPushButton { background: #dcfce7; color: #166534; font-size: 10.5px; "
            "font-weight: bold; border-radius: 4px; border: 1px solid #86efac; }"
            "QPushButton:hover { background: #bbf7d0; }"
        )
        self.btn_export.clicked.connect(self._export_json)
        btn_row.addWidget(self.btn_export, 1, 0, 1, 2)
        btn_row.setColumnStretch(0, 1)
        btn_row.setColumnStretch(1, 1)

        ctrl_lay.addLayout(btn_row)
        # Added below the scroll area so render controls remain pinned.

        # 4. FFmpeg log
        grp_log = CollapsibleSection("📝  Log FFmpeg")
        log_lay = QVBoxLayout()
        log_lay.setContentsMargins(4, 4, 4, 4)
        
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(100)
        self.log_text.setMinimumHeight(80)
        self.log_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log_text.setStyleSheet(
            "background: #f8fafc; color: #166534; font-family: monospace; font-size: 10px; border-radius: 4px; border: 1px solid #e2e8f0;"
        )
        log_lay.addWidget(self.log_text)
        
        self.btn_clear_log = QPushButton("Xóa log")
        self.btn_clear_log.setMinimumSize(72, 24)
        self.btn_clear_log.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.btn_clear_log.setStyleSheet("font-size: 10px; padding: 0;")
        self.btn_clear_log.clicked.connect(self.log_text.clear)
        log_lay.addWidget(self.btn_clear_log)
        grp_log.body_layout.addLayout(log_lay)
        tab_export_lay.addWidget(grp_log)
        tab_export_lay.addStretch(1)

        for field in tab_export.findChildren((QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox)):
            if (
                isinstance(field.parentWidget(), (StackedField, QAbstractSpinBox))
                or field.objectName().startswith("qt_spinbox_")
            ):
                continue
            field.setMinimumWidth(84)
            if isinstance(field, (QSpinBox, QDoubleSpinBox)):
                field.setMaximumWidth(110)
                field.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
                field.setAlignment(Qt.AlignmentFlag.AlignRight)
            else:
                field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if isinstance(field, QComboBox):
                field.setSizeAdjustPolicy(
                    QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
                )
                field.setMinimumContentsLength(8)

        for label in (min_lbl, max_lbl, zoom_lbl):
            label.setMinimumWidth(56)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            label.setStyleSheet("font-size: 11px; color: #636366; border: none;")

        tab_export_scroll.setWidget(tab_export)
        tab_export_page = QWidget()
        tab_export_page_lay = QVBoxLayout(tab_export_page)
        tab_export_page_lay.setContentsMargins(0, 4, 0, 0)
        tab_export_page_lay.setSpacing(8)
        tab_export_page_lay.addWidget(tab_export_scroll, 1)
        tab_export_page_lay.addWidget(grp_ctrl, 0)
        self.inspector_tab_widget.addTab(tab_export_page, "Cài đặt xuất")

        lay.addWidget(self.inspector_tab_widget, 1)
        return panel

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _apply_saved_settings(self):
        s = self._settings
        self._apply_workspace_state(s)

    def _apply_workspace_state(self, s: dict):
        self._unchecked_audio_files = set(s.get("unchecked_audio_files", []))
        self._unchecked_video_files = set(s.get("unchecked_video_files", []))

        saved_bg_files = s.get("bg_files", [])
        if isinstance(saved_bg_files, list) and saved_bg_files:
            self.pick_bg.set_selected_files(saved_bg_files)
            self._log_debug(f"Restored {len(saved_bg_files)} saved background videos")
        else:
            self.pick_bg.set_value(s.get("bg_folder", ""))
        self.pick_output.set_value(s.get("output_folder", ""))

        # Restore Edit Video Folder paths and selected files
        self.pick_vid_src.set_value(s.get("vid_src_folder", ""))
        vid_src_files = s.get("vid_src_files", [])
        if isinstance(vid_src_files, list) and vid_src_files:
            self.pick_vid_src.set_selected_files(vid_src_files)
            self._log_debug(f"Restored {len(vid_src_files)} video source files")
        
        self.pick_vid_bg.set_value(s.get("vid_bg_folder", ""))
        vid_bg_files = s.get("vid_bg_files", [])
        if isinstance(vid_bg_files, list) and vid_bg_files:
            self.pick_vid_bg.set_selected_files(vid_bg_files)
            self._log_debug(f"Restored {len(vid_bg_files)} video background files")

        saved_audio_files = s.get("audio_files", [])
        if isinstance(saved_audio_files, list) and saved_audio_files:
            self.pick_audio.set_selected_files(saved_audio_files)
            self._log_debug(f"Restored {len(saved_audio_files)} saved audio files")

        saved_srt_files = s.get("srt_files", [])
        if isinstance(saved_srt_files, list) and saved_srt_files:
            self.pick_srt.set_selected_files(saved_srt_files)
            self._log_debug(f"Restored {len(saved_srt_files)} saved SRT files")

        # Load subtitle style from saved settings
        preset = SubtitleStylePreset(
            name="Restored",
            font_name=s.get("font_name", "Arial"),
            font_size=s.get("font_size", 40),
            font_color=s.get("font_color", "#FFFFFF"),
            stroke_color=s.get("stroke_color", "#000000"),
            stroke_width=s.get("stroke_width", 2.0),
            stroke_enabled=s.get("stroke_enabled", True),
            bg_color=s.get("bg_color", "#000000"),
            bg_opacity=s.get("bg_opacity", 0.6),
            bg_padding_x=s.get("bg_padding_x", s.get("outline_size", 12)),
            bg_padding_y=s.get("bg_padding_y", 4),
            bg_corner_radius=s.get("bg_corner_radius", 4),
            bg_enabled=s.get("bg_enabled", True),
            shadow_color=s.get("shadow_color", "#000000"),
            shadow_opacity=s.get("shadow_opacity", 0.8),
            shadow_angle=s.get("shadow_angle", 45.0),
            shadow_distance=s.get("shadow_distance", 3.0),
            shadow_blur=s.get("shadow_blur", 2.0),
            shadow_enabled=s.get("shadow_enabled", False),
            alignment=s.get("subtitle_alignment", 2),
            margin_v=s.get("margin_v", 50),
            margin_l=s.get("margin_l", 20),
            margin_r=s.get("margin_r", 20),
        )
        self.style_panel.load_from_style(preset)

        self.cmb_resolution.setCurrentIndex(s.get("resolution", 0))
        self.spn_concurrent.setValue(s.get("max_concurrent_renders", 2))
        self.spn_slow_min.setValue(s.get("slow_min", 35.0))
        self.spn_slow_max.setValue(s.get("slow_max", 45.0))
        bg_zoom_val = float(s.get("bg_zoom", 100.0))
        self.spn_bg_zoom.setValue(bg_zoom_val)
        self._on_bg_zoom_changed(bg_zoom_val)

        # Tolerate legacy int-saved fps values (30) and the old "23" for 23.976.
        _fps_saved = str(s.get("fps", "30"))
        idx = self.cmb_fps.findData(_fps_saved)
        if idx < 0 and _fps_saved in ("23", "23.976"):
            idx = self.cmb_fps.findData("24000/1001")
        if idx < 0:
            idx = self.cmb_fps.findData(str(int(float(_fps_saved)))) if _fps_saved.replace(".", "").isdigit() else -1
        self.cmb_fps.setCurrentIndex(idx if idx >= 0 else 2)

        codec_val = s.get("codec", "hevc_nvenc")
        for i, (_, val) in enumerate(CODECS):
            if val == codec_val:
                self.cmb_codec.setCurrentIndex(i)
                break

        self._load_presets()

        # Restore logo settings (5 layers)
        for idx, ctrl in enumerate(self.logo_layers):
            layer_num = idx + 1
            ctrl.chk_enabled.setChecked(s.get(f"logo_enabled_{layer_num}", False))
            
            src_type = s.get(f"logo_source_type_{layer_num}", 2) # Default to Static file
            ctrl.cmb_source_type.setCurrentIndex(src_type)
            
            path_val = s.get(f"logo_path_{layer_num}", "")
            ctrl.edit_path.setText(path_val)
            
            # Restore logo_position directly 1:1 from combobox index (0: Center, 1: BR, 2: BL, 3: TR, 4: TL)
            ctrl.cmb_pos.setCurrentIndex(s.get(f"logo_position_{layer_num}", 0))
            
            ctrl.spn_size.setValue(s.get(f"logo_size_{layer_num}", 100))
            ctrl.spn_opacity.setValue(s.get(f"logo_opacity_{layer_num}", 90))
            
            ctrl.spn_margin_t.setValue(s.get(f"logo_margin_t_{layer_num}", 20))
            ctrl.spn_margin_b.setValue(s.get(f"logo_margin_b_{layer_num}", 20))
            ctrl.spn_margin_l.setValue(s.get(f"logo_margin_l_{layer_num}", 20))
            ctrl.spn_margin_r.setValue(s.get(f"logo_margin_r_{layer_num}", 20))
            
            ctrl.spn_crop_t.setValue(s.get(f"logo_crop_t_{layer_num}", 0))
            ctrl.spn_crop_b.setValue(s.get(f"logo_crop_b_{layer_num}", 0))
            ctrl.spn_crop_l.setValue(s.get(f"logo_crop_l_{layer_num}", 0))
            ctrl.spn_crop_r.setValue(s.get(f"logo_crop_r_{layer_num}", 0))
            ctrl.set_crop_mode_checked(s.get(f"logo_crop_mode_{layer_num}", False))
            ctrl.spn_speed.setValue(s.get(f"logo_speed_{layer_num}", 100))
            
            ctrl.chk_chroma_enabled.setChecked(s.get(f"logo_chroma_enabled_{layer_num}", False))
            ctrl.spn_chroma_sim.setValue(s.get(f"logo_chroma_sim_{layer_num}", 0.38))
            ctrl.spn_chroma_blend.setValue(s.get(f"logo_chroma_blend_{layer_num}", 0.08))
            ctrl.set_chroma_color(s.get(f"logo_chroma_color_{layer_num}", "#00FF00"))
            ctrl.spn_chroma_spill.setValue(s.get(f"logo_chroma_spill_{layer_num}", 0.0))
            ctrl.chroma_params_frame.setVisible(ctrl.chk_chroma_enabled.isChecked())

            ctrl.chk_luma_enabled.setChecked(s.get(f"logo_luma_enabled_{layer_num}", False))
            ctrl.spn_luma_threshold.setValue(s.get(f"logo_luma_threshold_{layer_num}", 0.10))
            ctrl.spn_luma_tolerance.setValue(s.get(f"logo_luma_tolerance_{layer_num}", 0.05))
            ctrl.spn_luma_softness.setValue(s.get(f"logo_luma_softness_{layer_num}", 0.05))
            ctrl.luma_params_frame.setVisible(ctrl.chk_luma_enabled.isChecked())
            ctrl.color_panel.set_config(s.get(f"logo_color_grade_{layer_num}"))

            ctrl._update_speed_visibility()
            
        self._on_logo_settings_changed()

        # Restore Edit Video layers (5 layers)
        for idx, widget in enumerate(self.video_layer_widgets):
            layer_num = idx + 1
            is_l1 = (layer_num == 1)
            widget.chk_enabled.setChecked(s.get(f"vlayer_enabled_{layer_num}", is_l1))
            widget.cmb_source_type.setCurrentIndex(s.get(f"vlayer_source_type_{layer_num}", 0 if is_l1 else 1))
            widget.edit_path.setText(s.get(f"vlayer_path_{layer_num}", ""))
            
            widget.cmb_pos.setCurrentIndex(s.get(f"vlayer_position_{layer_num}", 0))
            widget.spn_size.setValue(s.get(f"vlayer_size_{layer_num}", 100))
            widget.spn_opacity.setValue(s.get(f"vlayer_opacity_{layer_num}", 100))
            
            widget.spn_margin_t.setValue(s.get(f"vlayer_margin_t_{layer_num}", 0))
            widget.spn_margin_b.setValue(s.get(f"vlayer_margin_b_{layer_num}", 0))
            widget.spn_margin_l.setValue(s.get(f"vlayer_margin_l_{layer_num}", 0))
            widget.spn_margin_r.setValue(s.get(f"vlayer_margin_r_{layer_num}", 0))
            
            widget.spn_crop_t.setValue(s.get(f"vlayer_crop_t_{layer_num}", 0))
            widget.spn_crop_b.setValue(s.get(f"vlayer_crop_b_{layer_num}", 0))
            widget.spn_crop_l.setValue(s.get(f"vlayer_crop_l_{layer_num}", 0))
            widget.spn_crop_r.setValue(s.get(f"vlayer_crop_r_{layer_num}", 0))
            widget.set_crop_mode_checked(s.get(f"vlayer_crop_mode_{layer_num}", False))
            widget.spn_speed.setValue(s.get(f"vlayer_speed_{layer_num}", 100))
            
            widget.chk_chroma_enabled.setChecked(s.get(f"vlayer_chroma_enabled_{layer_num}", False))
            widget.spn_chroma_sim.setValue(s.get(f"vlayer_chroma_sim_{layer_num}", 0.38))
            widget.spn_chroma_blend.setValue(s.get(f"vlayer_chroma_blend_{layer_num}", 0.08))
            widget.set_chroma_color(s.get(f"vlayer_chroma_color_{layer_num}", "#00FF00"))
            widget.spn_chroma_spill.setValue(s.get(f"vlayer_chroma_spill_{layer_num}", 0.0))
            widget.chroma_params_frame.setVisible(widget.chk_chroma_enabled.isChecked())

            widget.chk_luma_enabled.setChecked(s.get(f"vlayer_luma_enabled_{layer_num}", False))
            widget.spn_luma_threshold.setValue(s.get(f"vlayer_luma_threshold_{layer_num}", 0.10))
            widget.spn_luma_tolerance.setValue(s.get(f"vlayer_luma_tolerance_{layer_num}", 0.05))
            widget.spn_luma_softness.setValue(s.get(f"vlayer_luma_softness_{layer_num}", 0.05))
            widget.luma_params_frame.setVisible(widget.chk_luma_enabled.isChecked())
            if f"vlayer_color_grade_{layer_num}" in s:
                widget.color_panel.set_config(s.get(f"vlayer_color_grade_{layer_num}"))

            widget._update_speed_visibility()

        self._on_video_layer_changed()

        self._on_video_layer_changed()

        # Restore active mode tab
        active_tab_mode = s.get("active_tab_mode", "sub")
        if active_tab_mode == "video":
            self._on_mode_video_clicked()
        else:
            self._on_mode_sub_clicked()

        # Restore active presets and layer tabs
        active_preset_name = s.get("active_preset_name", "")
        if active_preset_name:
            idx = self.cmb_preset.findText(active_preset_name)
            if idx >= 0:
                self.cmb_preset.setCurrentIndex(idx)

        if hasattr(self, "layer_tab_widget"):
            self.layer_tab_widget.setCurrentIndex(0)
        if hasattr(self, "video_tab_widget"):
            self.video_tab_widget.setCurrentIndex(0)
        if hasattr(self, "inspector_tab_widget"):
            self.inspector_tab_widget.setCurrentIndex(0)

        # setCurrentIndex is a no-op when the index is unchanged, so sync each
        # preview's crop-edit state to the active layer's restored toggle here.
        if hasattr(self, "video_layout_preview") and self.video_layer_widgets:
            _vi = self.video_tab_widget.currentIndex()
            if 0 <= _vi < len(self.video_layer_widgets):
                self.video_layout_preview.set_crop_mode(self.video_layer_widgets[_vi].btn_crop_mode.isChecked())
        if hasattr(self, "preview_widget") and self.logo_layers:
            _li = self.layer_tab_widget.currentIndex()
            if 0 <= _li < len(self.logo_layers) and hasattr(self.preview_widget, "set_crop_mode"):
                self.preview_widget.set_crop_mode(self.logo_layers[_li].btn_crop_mode.isChecked())

        # Auto-scan if files already set
        if self.pick_audio.selected_files() and self.pick_srt.selected_files():
            self._scan_pairs()

        # Restore selected rows in tables
        selected_audio_row = s.get("selected_audio_row", -1)
        if selected_audio_row >= 0 and selected_audio_row < self.pair_table.rowCount():
            self.pair_table.selectRow(selected_audio_row)

        selected_video_row = s.get("selected_video_row", -1)
        if selected_video_row >= 0 and selected_video_row < self.vid_batch_table.rowCount():
            self.vid_batch_table.selectRow(selected_video_row)

        # Trigger resolution update on preview widgets after settings load
        self._on_resolution_changed()

    def _auto_export_json(self):
        if not self._pairs:
            return
        data = {
            "folders": {
                "bg_folder": self.pick_bg.value(),
                "bg_files": self.pick_bg.selected_files(),
                "audio_files": self.pick_audio.selected_files(),
                "srt_files": self.pick_srt.selected_files(),
                "output_folder": self.pick_output.value(),
            },
            "subtitle": self.style_panel.get_style().to_dict(),
            "render": {
                "codec": CODECS[self.cmb_codec.currentIndex()][1],
                "slow_min": self.spn_slow_min.value(),
                "slow_max": self.spn_slow_max.value(),
                "bg_zoom": self.spn_bg_zoom.value(),
            },
            "pairs": [
                {
                    "index": p.index,
                    "audio": p.audio_path,
                    "srt": p.srt_path,
                    "matched": p.matched,
                    "error": p.error,
                }
                for p in self._pairs
            ],
        }
        try:
            with open(EXPORT_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _serialize_workspace_state(self) -> dict:
        style = self.style_panel.get_style()
        settings_dict = {
            "bg_folder": self.pick_bg.value(),
            "bg_files": self.pick_bg.selected_files(),
            "audio_files": self.pick_audio.selected_files(),
            "srt_files": self.pick_srt.selected_files(),
            "output_folder": self.pick_output.value(),
            "vid_src_folder": self.pick_vid_src.value(),
            "vid_src_files": self.pick_vid_src.selected_files(),
            "vid_bg_folder": self.pick_vid_bg.value(),
            "vid_bg_files": self.pick_vid_bg.selected_files(),
            "font_name": style.font_name,
            "font_size": style.font_size,
            "font_color": style.font_color,
            "stroke_color": style.stroke_color,
            "stroke_width": style.stroke_width,
            "stroke_enabled": style.stroke_enabled,
            "bg_color": style.bg_color,
            "bg_opacity": style.bg_opacity,
            "bg_padding_x": style.bg_padding_x,
            "bg_padding_y": style.bg_padding_y,
            "bg_corner_radius": style.bg_corner_radius,
            "bg_enabled": style.bg_enabled,
            "shadow_color": style.shadow_color,
            "shadow_opacity": style.shadow_opacity,
            "shadow_angle": style.shadow_angle,
            "shadow_distance": style.shadow_distance,
            "shadow_blur": style.shadow_blur,
            "shadow_enabled": style.shadow_enabled,
            "outline_size": style.bg_padding_x,  # legacy alias
            "margin_v": style.margin_v,
            "margin_l": style.margin_l,
            "margin_r": style.margin_r,
            "resolution": self.cmb_resolution.currentIndex(),
            "slow_min": self.spn_slow_min.value(),
            "slow_max": self.spn_slow_max.value(),
            "bg_zoom": self.spn_bg_zoom.value(),
            "codec": CODECS[self.cmb_codec.currentIndex()][1],
            "fps": self.cmb_fps.currentData(),
            "use_gpu": True,
            "subtitle_alignment": style.alignment,
            "max_concurrent_renders": self.spn_concurrent.value(),
        }

        # Save logo settings (5 layers)
        for idx, ctrl in enumerate(self.logo_layers):
            layer_num = idx + 1
            cfg_obj = ctrl.get_config()
            settings_dict[f"logo_enabled_{layer_num}"] = cfg_obj.enabled
            settings_dict[f"logo_source_type_{layer_num}"] = ctrl.cmb_source_type.currentIndex()
            settings_dict[f"logo_path_{layer_num}"] = ctrl.edit_path.text()
            settings_dict[f"logo_position_{layer_num}"] = ctrl.cmb_pos.currentIndex()
            settings_dict[f"logo_size_{layer_num}"] = cfg_obj.size
            settings_dict[f"logo_opacity_{layer_num}"] = int(cfg_obj.opacity * 100)
            settings_dict[f"logo_margin_t_{layer_num}"] = cfg_obj.margin_t
            settings_dict[f"logo_margin_b_{layer_num}"] = cfg_obj.margin_b
            settings_dict[f"logo_margin_l_{layer_num}"] = cfg_obj.margin_l
            settings_dict[f"logo_margin_r_{layer_num}"] = cfg_obj.margin_r
            settings_dict[f"logo_crop_t_{layer_num}"] = cfg_obj.crop_t
            settings_dict[f"logo_crop_b_{layer_num}"] = cfg_obj.crop_b
            settings_dict[f"logo_crop_l_{layer_num}"] = cfg_obj.crop_l
            settings_dict[f"logo_crop_r_{layer_num}"] = cfg_obj.crop_r
            settings_dict[f"logo_crop_mode_{layer_num}"] = ctrl.btn_crop_mode.isChecked()
            settings_dict[f"logo_speed_{layer_num}"] = ctrl.spn_speed.value()
            settings_dict[f"logo_chroma_enabled_{layer_num}"] = ctrl.chk_chroma_enabled.isChecked()
            settings_dict[f"logo_chroma_sim_{layer_num}"] = ctrl.spn_chroma_sim.value()
            settings_dict[f"logo_chroma_blend_{layer_num}"] = ctrl.spn_chroma_blend.value()
            settings_dict[f"logo_chroma_color_{layer_num}"] = ctrl.chroma_key_color
            settings_dict[f"logo_chroma_spill_{layer_num}"] = ctrl.spn_chroma_spill.value()
            settings_dict[f"logo_luma_enabled_{layer_num}"] = ctrl.chk_luma_enabled.isChecked()
            settings_dict[f"logo_luma_threshold_{layer_num}"] = ctrl.spn_luma_threshold.value()
            settings_dict[f"logo_luma_tolerance_{layer_num}"] = ctrl.spn_luma_tolerance.value()
            settings_dict[f"logo_luma_softness_{layer_num}"] = ctrl.spn_luma_softness.value()
            settings_dict[f"logo_color_grade_{layer_num}"] = ctrl.color_panel.get_config().to_dict()

        # Save Edit Video layers (5 layers)
        for idx, widget in enumerate(self.video_layer_widgets):
            layer_num = idx + 1
            cfg_obj = widget.get_config()
            settings_dict[f"vlayer_enabled_{layer_num}"] = cfg_obj.enabled
            settings_dict[f"vlayer_source_type_{layer_num}"] = widget.cmb_source_type.currentIndex()
            settings_dict[f"vlayer_path_{layer_num}"] = widget.edit_path.text()
            settings_dict[f"vlayer_position_{layer_num}"] = widget.cmb_pos.currentIndex()
            settings_dict[f"vlayer_size_{layer_num}"] = cfg_obj.size
            settings_dict[f"vlayer_opacity_{layer_num}"] = int(cfg_obj.opacity * 100)
            settings_dict[f"vlayer_margin_t_{layer_num}"] = cfg_obj.margin_t
            settings_dict[f"vlayer_margin_b_{layer_num}"] = cfg_obj.margin_b
            settings_dict[f"vlayer_margin_l_{layer_num}"] = cfg_obj.margin_l
            settings_dict[f"vlayer_margin_r_{layer_num}"] = cfg_obj.margin_r
            settings_dict[f"vlayer_crop_t_{layer_num}"] = cfg_obj.crop_t
            settings_dict[f"vlayer_crop_b_{layer_num}"] = cfg_obj.crop_b
            settings_dict[f"vlayer_crop_l_{layer_num}"] = cfg_obj.crop_l
            settings_dict[f"vlayer_crop_r_{layer_num}"] = cfg_obj.crop_r
            settings_dict[f"vlayer_crop_mode_{layer_num}"] = widget.btn_crop_mode.isChecked()
            settings_dict[f"vlayer_speed_{layer_num}"] = widget.spn_speed.value()
            settings_dict[f"vlayer_chroma_enabled_{layer_num}"] = widget.chk_chroma_enabled.isChecked()
            settings_dict[f"vlayer_chroma_sim_{layer_num}"] = widget.spn_chroma_sim.value()
            settings_dict[f"vlayer_chroma_blend_{layer_num}"] = widget.spn_chroma_blend.value()
            settings_dict[f"vlayer_chroma_color_{layer_num}"] = widget.chroma_key_color
            settings_dict[f"vlayer_chroma_spill_{layer_num}"] = widget.spn_chroma_spill.value()
            settings_dict[f"vlayer_luma_enabled_{layer_num}"] = widget.chk_luma_enabled.isChecked()
            settings_dict[f"vlayer_luma_threshold_{layer_num}"] = widget.spn_luma_threshold.value()
            settings_dict[f"vlayer_luma_tolerance_{layer_num}"] = widget.spn_luma_tolerance.value()
            settings_dict[f"vlayer_luma_softness_{layer_num}"] = widget.spn_luma_softness.value()
            settings_dict[f"vlayer_color_grade_{layer_num}"] = widget.color_panel.get_config().to_dict()

        # Collect unchecked audio files from pair_table
        unchecked_audio_files = []
        for row in range(self.pair_table.rowCount()):
            item = self.pair_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Unchecked:
                path = item.data(Qt.ItemDataRole.UserRole)
                if path:
                    unchecked_audio_files.append(path)
                    
        # Collect unchecked video files from vid_batch_table
        unchecked_video_files = []
        for row in range(self.vid_batch_table.rowCount()):
            item = self.vid_batch_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Unchecked:
                path = item.data(Qt.ItemDataRole.UserRole)
                if path:
                    unchecked_video_files.append(path)

        settings_dict["unchecked_audio_files"] = unchecked_audio_files
        settings_dict["unchecked_video_files"] = unchecked_video_files
        settings_dict["active_tab_mode"] = "video" if self.btn_tab_video.isChecked() else "sub"
        settings_dict["active_preset_name"] = self.cmb_preset.currentText()
        settings_dict["selected_audio_row"] = self.pair_table.currentRow()
        settings_dict["selected_video_row"] = self.vid_batch_table.currentRow()
        settings_dict["active_logo_tab"] = self.layer_tab_widget.currentIndex() if hasattr(self, "layer_tab_widget") else 0
        settings_dict["active_video_tab"] = self.video_tab_widget.currentIndex() if hasattr(self, "video_tab_widget") else 0
        settings_dict["active_inspector_tab"] = self.inspector_tab_widget.currentIndex() if hasattr(self, "inspector_tab_widget") else 0

        # Legacy fallback
        if self.logo_layers:
            layer1 = self.logo_layers[0].get_config()
            settings_dict["logo_path"] = layer1.path
            settings_dict["logo_files"] = [layer1.path] if layer1.path else []
            settings_dict["logo_position"] = layer1.position
            settings_dict["logo_size"] = layer1.size
            settings_dict["logo_opacity"] = int(layer1.opacity * 100)

        return settings_dict

    def _save_settings(self):
        settings_dict = self._serialize_workspace_state()
        # Remove per-layer configurations and temporary project paths from global settings.json
        keys_to_remove = [k for k in settings_dict if k.startswith("vlayer_") or k.startswith("logo_")]
        project_keys = [
            "audio_files", "srt_files", "vid_src_files", "vid_bg_files",
            "unchecked_audio_files", "unchecked_video_files",
            "bg_folder", "audio_folder", "srt_folder", "output_folder",
            "vid_src_folder", "vid_bg_folder", "vid_output_folder",
            "selected_audio_row", "selected_video_row", "bg_files",
            "logo_path", "logo_files"
        ]
        for key in project_keys + keys_to_remove:
            settings_dict.pop(key, None)
            
        cfg.save(settings_dict)
        self._auto_export_json()

    def _save_project_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu dự án", "", "EncoMie Project files (*.emie);;JSON files (*.json)"
        )
        if not path:
            return
        state = self._serialize_workspace_state()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            self._log_debug(f"Saved project file to {path}")
            QMessageBox.information(self, "Lưu dự án", "Đã lưu dự án thành công!")
        except Exception as e:
            self._log_debug(f"Failed to save project file: {e}")
            QMessageBox.critical(self, "Lỗi", f"Không thể lưu dự án: {e}")

    def _load_project_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Mở dự án", "", "EncoMie Project files (*.emie);;JSON files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self._apply_workspace_state(state)
            self._log_debug(f"Loaded project file from {path}")
            QMessageBox.information(self, "Mở dự án", "Đã tải dự án thành công!")
        except Exception as e:
            self._log_debug(f"Failed to load project file: {e}")
            QMessageBox.critical(self, "Lỗi", f"Không thể mở dự án: {e}")

    def closeEvent(self, event):
        self._save_settings()
        event.accept()

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất lựa chọn ra JSON", "selections.json",
            "JSON files (*.json)"
        )
        if not path:
            return

        matched_pairs = [
            {
                "index": p.index,
                "audio": p.audio_path,
                "srt": p.srt_path,
                "matched": p.matched,
                "error": p.error,
            }
            for p in self._pairs
        ]

        data = {
            "folders": {
                "bg_folder": self.pick_bg.value(),
                "bg_files": self.pick_bg.selected_files(),
                "audio_files": self.pick_audio.selected_files(),
                "srt_files": self.pick_srt.selected_files(),
                "output_folder": self.pick_output.value(),
            },
            "subtitle": self.style_panel.get_style().to_dict(),
            "render": {
                "codec": CODECS[self.cmb_codec.currentIndex()][1],
                "slow_min": self.spn_slow_min.value(),
                "slow_max": self.spn_slow_max.value(),
                "bg_zoom": self.spn_bg_zoom.value(),
            },
            "pairs": matched_pairs,
        }

        try:
            import json
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.statusBar().showMessage(f"Đã xuất ra {path}", 5000)
            self._log(f"📤 Đã xuất lựa chọn ra {path}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi xuất JSON", str(e))

    # ------------------------------------------------------------------
    # Logic
    # ------------------------------------------------------------------

    def _check_deps(self):
        from utils.gpu_detect import check_ffmpeg, check_ffprobe
        issues = []
        if not check_ffmpeg():
            issues.append("• FFmpeg không tìm thấy — hãy cài FFmpeg và thêm vào PATH")
        if not check_ffprobe():
            issues.append("• FFprobe không tìm thấy — thường đi kèm FFmpeg")
        if issues:
            QMessageBox.warning(self, "Thiếu phụ thuộc", "\n".join(issues))

    def _on_file_selection_change(self, _value):
        self._log_debug(
            f"File selection changed | bg={len(self.pick_bg.selected_files())} | media={len(self.pick_audio.selected_files())} | srt={len(self.pick_srt.selected_files())}"
        )
        if self.pick_audio.selected_files() and self.pick_srt.selected_files():
            self._scan_pairs()

    def _scan_pairs(self):
        media_files = self.pick_audio.selected_files()
        srt_files = self.pick_srt.selected_files()
        self._log_debug(f"Scanning pairs | media_files={len(media_files)} | srt_files={len(srt_files)}")
        if not media_files or not srt_files:
            self._log_debug("Scan skipped because media or srt list is empty")
            return

        self.lbl_pair_summary.setText("Đang quét…")
        try:
            pairs = build_pairs(media_files, srt_files)
            self._log_debug(f"Built {len(pairs)} pairs successfully")
            self._on_pairs_ready(pairs)
        except Exception as e:
            self._log_debug(f"Pair scan failed: {e}")
            self.lbl_pair_summary.setText(f"Lỗi: {e}")

    def _on_pairs_ready(self, pairs: list[FilePair]):
        self._pairs = pairs
        unchecked_audios = getattr(self, "_unchecked_audio_files", set())
        self.pair_table.load_pairs(pairs, unchecked_audios)
        
        total = len(pairs)
        matched_clean = sum(1 for p in pairs if p.matched and not p.error)
        mismatched = sum(1 for p in pairs if p.matched and p.error == "Lệch file")
        missing = sum(1 for p in pairs if not p.matched)

        summary = f"Tìm thấy {total} file  —  {matched_clean} khớp ✓"
        if mismatched:
            summary += f"  —  {mismatched} lệch file ⚠️"
        if missing:
            summary += f"  —  {missing} thiếu tệp ✗"

        self._log_debug(f"Pair summary: {summary}")
        self.lbl_pair_summary.setText(summary)
        self._auto_export_json()

        # Automatically select the first row to trigger the preview
        if total > 0:
            self.pair_table.selectRow(0)

    # ------------------------------------------------------------------
    # Subtitle editor integration (Phase 1 + Phase 4)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Preset management (Phase 3)
    # ------------------------------------------------------------------

    def _load_presets(self):
        """Load style presets into the combo box."""
        self._presets = StylePresetService.load_all()
        self.cmb_preset.blockSignals(True)
        self.cmb_preset.clear()
        for p in self._presets:
            self.cmb_preset.addItem(p.name)
        self.cmb_preset.blockSignals(False)

    def _on_preset_changed(self, index: int):
        """Apply selected preset to the style panel."""
        if index < 0 or index >= len(self._presets):
            return
        preset = self._presets[index]
        self.style_panel.load_from_style(preset)
        if hasattr(self.style_panel, "_cmb_preset"):
            self.style_panel._cmb_preset.setCurrentText(preset.name)
        self._active_preset = preset

    def _on_delete_preset_inline(self):
        """Delete current preset from both editor and main preset list."""
        name = self.style_panel._cmb_preset.currentText()
        if not name:
            return
        if name in self.style_panel.PRESETS_BUILTIN:
            QMessageBox.information(
                self, "Xóa preset",
                "Preset mặc định không thể xóa."
            )
            return
        self.style_panel._delete_preset()
        idx = self.cmb_preset.findText(name)
        if idx >= 0:
            self.cmb_preset.removeItem(idx)

    def _on_reset_defaults_inline(self):
        """Reset current preset back to built-in default."""
        self.style_panel._reset_defaults()
        self.cmb_preset.setCurrentText("Classic")
        if hasattr(self.style_panel, "_on_changed"):
            self.style_panel._on_changed()

    def _on_save_preset(self):
        """Save current style as a new preset."""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Luu Preset Style", "Ten preset moi:",
            text=self.style_panel.get_style().name
        )
        if not ok or not name.strip():
            return
        style = self.style_panel.get_style()
        preset = SubtitleStylePreset(
            name=name.strip(),
            font_name=style.font_name,
            font_size=style.font_size,
            font_color=style.font_color,
            stroke_color=style.stroke_color,
            stroke_width=style.stroke_width,
            stroke_enabled=style.stroke_enabled,
            bg_color=style.bg_color,
            bg_opacity=style.bg_opacity,
            bg_padding_x=style.bg_padding_x,
            bg_padding_y=style.bg_padding_y,
            bg_corner_radius=style.bg_corner_radius,
            bg_enabled=style.bg_enabled,
            shadow_color=style.shadow_color,
            shadow_opacity=style.shadow_opacity,
            shadow_angle=style.shadow_angle,
            shadow_distance=style.shadow_distance,
            shadow_blur=style.shadow_blur,
            shadow_enabled=style.shadow_enabled,
            alignment=style.alignment,
            margin_v=style.margin_v,
            margin_l=style.margin_l,
            margin_r=style.margin_r,
        )
        self._presets = StylePresetService.add_preset(preset)
        self.cmb_preset.addItem(name.strip())
        self.cmb_preset.setCurrentIndex(self.cmb_preset.count() - 1)

    # ------------------------------------------------------------------
    # Render config
    # ------------------------------------------------------------------

    def _build_config(self) -> RenderConfig:
        codec_val = CODECS[self.cmb_codec.currentIndex()][1]
        res_val = self.cmb_resolution.currentText().split(" ")[0]
        fps_val = str(self.cmb_fps.currentData() or "30")
        
        if self.btn_tab_video.isChecked():
            # Edit Video mode configurations
            configs = []
            for ctrl in self.video_layer_widgets:
                configs.append(ctrl.get_config())
                
            return RenderConfig(
                bg_folder="",
                bg_videos=self.pick_vid_bg.selected_files(),
                audio_folder="",
                srt_folder="",
                output_folder=self.pick_output.value(),
                subtitle_style=SubtitleStyle(font_size=0, stroke_enabled=False, bg_enabled=False),
                slow_min=self.spn_slow_min.value(),
                slow_max=self.spn_slow_max.value(),
                bg_zoom=self.spn_bg_zoom.value(),
                codec=codec_val,
                use_gpu="nvenc" in codec_val,
                logo_path=None,
                layers=configs,
                resolution=res_val,
                fps=fps_val,
                max_concurrent_renders=self.spn_concurrent.value(),
            )
        else:
            preset = self.style_panel.get_style()
            style = SubtitleStyle.from_preset(preset)
            
            configs = []
            for ctrl in self.logo_layers:
                configs.append(ctrl.get_config())
                
            layer1 = configs[0] if configs else None
            
            return RenderConfig(
                bg_folder=self.pick_bg.value(),
                bg_videos=self.pick_bg.selected_files(),
                audio_folder=self.pick_audio.value(),
                srt_folder=self.pick_srt.value(),
                output_folder=self.pick_output.value(),
                subtitle_style=style,
                slow_min=self.spn_slow_min.value(),
                slow_max=self.spn_slow_max.value(),
                bg_zoom=self.spn_bg_zoom.value(),
                codec=codec_val,
                use_gpu="nvenc" in codec_val,
                logo_path=layer1.path if (layer1 and layer1.enabled) else None,
                logo_position=layer1.position if layer1 else 0,
                logo_size=layer1.size if layer1 else 100,
                logo_opacity=layer1.opacity if layer1 else 0.8,
                layers=configs,
                resolution=res_val,
                fps=fps_val,
                max_concurrent_renders=self.spn_concurrent.value(),
            )

    def _validate(self) -> bool:
        errs = []
        if not self.pick_output.value():
            errs.append("• Chưa chọn thư mục Output (ở tab Cài đặt xuất)")

        if self.btn_tab_video.isChecked():
            # Validate Edit Video mode
            if not self.pick_vid_src.value():
                errs.append("• Chưa chọn thư mục video nguồn để scale")
            if not self._pairs:
                errs.append("• Chưa có video nào trong danh sách (hãy quét lại)")
        else:
            # Validate Edit Sub mode
            if not self.pick_bg.value() and not self.pick_bg.selected_files():
                errs.append("• Chưa chọn Video nền hoặc folder chứa video nền")
            if not self.pick_audio.selected_files():
                errs.append("• Chưa chọn file media nguồn")
            if not self.pick_srt.selected_files():
                errs.append("• Chưa chọn file Subtitle SRT")
            if not self._pairs:
                errs.append("• Chưa có file nào được ghép (hãy quét lại)")
            matched = [p for p in self._pairs if p.matched]
            if not matched:
                errs.append("• Không có cặp file audio+SRT hợp lệ nào")
                
        if errs:
            QMessageBox.warning(self, "Chưa đủ thông tin", "\n".join(errs))
            return False
        return True

    def _start_render(self):
        if not self._guard_license_active():
            return
        if not self._validate():
            return

        self._save_timer.stop()
        self._save_settings()

        config = self._build_config()

        # Clamp output to what the signed license token actually permits.
        from core.entitlements import apply_to_render_config
        _wanted_gpu = bool(getattr(config, "use_gpu", False))
        ent = apply_to_render_config(config, getattr(self, "_license_info", None))
        if _wanted_gpu and not ent.gpu:
            self._on_log("[Bản quyền] Gói hiện tại không hỗ trợ tăng tốc GPU - đã chuyển về CPU encoder.")

        os.makedirs(config.output_folder, exist_ok=True)
        # Filter matching pairs based on active tab and checked rows
        matched_pairs = []
        table = self.vid_batch_table if self.btn_tab_video.isChecked() else self.pair_table
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                if row < len(self._pairs):
                    p = self._pairs[row]
                    if p.matched:
                        matched_pairs.append(p)

        if not matched_pairs:
            QMessageBox.warning(self, "Cảnh báo", "Bạn chưa chọn bất kỳ video nào để render!")
            return

        self._worker = RenderWorker(matched_pairs, config, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.log_line.connect(self._on_log)
        self._worker.pair_done.connect(self._on_pair_done)
        self._worker.pair_error.connect(self._on_pair_error)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.license_expired.connect(self._on_render_license_expired)
        self._worker.quota_exceeded.connect(self._on_render_quota_exceeded)
        self._worker.stopped.connect(self._on_stopped)
        self._worker.paused.connect(self._on_paused)
        self._worker.resumed.connect(self._on_resumed)

        self.btn_render.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("⏸  Tạm dừng")
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self._log(f"Bắt đầu render {len(matched_pairs)} video...")
        self._log(f"Codec: {config.codec}  |  GPU: {config.use_gpu}")
        self._log("-" * 60)

        self._worker.start()

    def _toggle_pause_render(self):
        if not self._worker:
            return
        if self.btn_pause.text().startswith("⏸"):
            self._worker.pause()
        else:
            self._worker.resume()

    def _stop_render(self):
        if self._worker:
            self._worker.abort()
            self.btn_pause.setEnabled(False)
            self.btn_stop.setEnabled(False)
            self.lbl_status.setText("Đang dừng…")

    def _on_paused(self):
        self.btn_pause.setText("▶  Tiếp tục")
        self.lbl_status.setText("Đã tạm dừng")
        self._log("--- Render tạm dừng ---")

    def _on_resumed(self):
        self.btn_pause.setText("⏸  Tạm dừng")
        self.lbl_status.setText("Đang tiếp tục render…")
        self._log("--- Render tiếp tục ---")

    def _on_progress(self, pct: float, msg: str):
        self.progress_bar.setValue(round(pct))
        self.lbl_status.setText(msg)

    def _on_log(self, line: str):
        # Only show meaningful lines (filter out very verbose FFmpeg stats)
        if any(k in line for k in ["frame=", "fps=", "bitrate=", "speed="]):
            return  # skip per-frame stats spam; progress bar handles it
        self._log(line)

    def _log(self, text: str):
        self.log_text.appendPlainText(text)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_pair_done(self, index: str, output: str):
        self._log(f"✓ [{index}] Xong → {Path(output).name}")

    def _on_pair_error(self, index: str, error: str):
        self._log(f"✗ [{index}] Lỗi: {error}")

    def _on_all_done(self, success: int, errors: int):
        self.btn_render.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸  Tạm dừng")
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(100)
        msg = f"Hoàn thành! {success} video thành công"
        if errors:
            msg += f", {errors} lỗi"
        self.lbl_status.setText(msg)
        self._log("=" * 60)
        self._log(msg)
        QMessageBox.information(self, "Hoàn thành", msg)

    def _on_stopped(self):
        self.btn_render.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸  Tạm dừng")
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("Đã dừng")
        self._log("--- Render bị dừng bởi người dùng ---")

    def _on_render_license_expired(self, msg: str):
        self.btn_render.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸  Tạm dừng")
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("Tạm dừng render do hết hạn bản quyền")
        self._log("=" * 60)
        self._log(f"⚠️ {msg}")
        QMessageBox.warning(
            self,
            "Bản Quyền Hết Hạn",
            f"{msg}\nVui lòng kích hoạt key mới để tiếp tục render các video còn lại."
        )
        self._show_license_window(mandatory=True)

    def _on_render_quota_exceeded(self, msg: str):
        self.btn_render.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸  Tạm dừng")
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("Tạm dừng render do đạt giới hạn gói Free")
        self._log("=" * 60)
        self._log(f"⚠️ {msg}")
        QMessageBox.information(self, "Đã Đạt Giới Hạn Gói Free", msg)

    def _on_refresh_preview_frame(self):
        """Extract a frame asynchronously from the first selected video and set it as preview background."""
        video_files = self.pick_bg.selected_files()
        if not hasattr(self, "preview_widget"):
            return
        if not video_files:
            self.preview_widget.set_frame(None)
            return
        path = video_files[0]
        if not os.path.exists(path):
            self.preview_widget.set_frame(None)
            return
        if not hasattr(self, "_video_frame_cache"):
            self._video_frame_cache = {}
        if path in self._video_frame_cache:
            self.preview_widget.set_frame(self._video_frame_cache[path])
            return
        if path in self.running_extractions:
            return
        self.running_extractions.add(path)
        task = FrameExtractTask(path)
        task.signals.loaded.connect(self._on_sub_preview_frame_loaded)
        self.frame_pool.start(task)

    def _on_sub_preview_frame_loaded(self, path: str, image: QImage):
        if path in self.running_extractions:
            self.running_extractions.remove(path)
        if image and not image.isNull():
            self._add_frame_to_cache(path, image)
            video_files = self.pick_bg.selected_files()
            if video_files and video_files[0] == path and hasattr(self, "preview_widget"):
                self.preview_widget.set_frame(self._video_frame_cache.get(path, image))

    def _on_pair_selection_changed(self):
        """Update preview background and subtitle text when a pair is selected in the table."""
        selected_ranges = self.pair_table.selectedRanges()
        if not selected_ranges:
            return
        row = selected_ranges[0].topRow()
        if row < 0 or row >= len(self._pairs):
            return

        pair = self._pairs[row]
        if not pair.matched:
            return

        # 1. Load SRT file to preview
        if pair.srt_path and os.path.exists(pair.srt_path):
            self.style_panel.reload_srt(pair.srt_path)

        # 2. Extract a frame from the first background video as preview
        self._on_refresh_preview_frame()

    def _on_first_sub_to_zero(self):
        """Shift the entire subtitle timeline so the first subtitle starts at 0s."""
        srt_files = self.pick_srt.selected_files()
        if not srt_files:
            QMessageBox.information(self, "Dời về 0s", "Chưa có file SRT nào được chọn.")
            return

        reply = QMessageBox.question(
            self, "Dời về 0s",
            f"Shift toàn bộ timeline của {len(srt_files)} file SRT về 0s?\n"
            "Thời gian bắt đầu đầu tiên sẽ được trừ đi khỏi mọi subtitle.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        changed = 0
        total_offset_ms = 0
        errors = []
        for path in srt_files:
            try:
                entries = SrtService.parse(path)
                if not entries:
                    errors.append(f"{Path(path).name}: file rỗng")
                    continue
                self._timing_undo[path] = entries[:]
                new_entries, offset_ms = SrtService.shift_to_zero(entries)
                SrtService.write(path, new_entries)
                changed += 1
                total_offset_ms = offset_ms  # same for all files in the set
            except Exception as e:
                errors.append(f"{Path(path).name}: {e}")

        if changed:
            self.btn_undo_timing.setEnabled(True)
            offset_s = total_offset_ms / 1000.0
            QMessageBox.information(
                self, "Dời về 0s",
                f"Shifted subtitle timeline by -{offset_s:.3f} seconds.\n"
                f"Đã xử lý {changed} file."
            )
            self._scan_pairs()
            if srt_files:
                self.style_panel.reload_srt_entries(srt_files[0])
                if hasattr(self, "preview_widget"):
                    self.preview_widget.reload_srt_entries(srt_files[0])
        elif errors:
            QMessageBox.warning(self, "Dời về 0s", f"Lỗi: {', '.join(errors)}")
        self._log(f"[Timing] Shift to 0s: {changed} file, offset=-{total_offset_ms}ms")

    def _on_undo_timing(self):
        """Restore SRT files to their state before the last timing change."""
        if not self._timing_undo:
            return
        reply = QMessageBox.question(
            self, "Hoàn tác", f"Hoàn tác {len(self._timing_undo)} file về trạng thái trước đó?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        restored = 0
        errors = []
        for path, entries in self._timing_undo.items():
            try:
                SrtService.write(path, entries)
                restored += 1
            except Exception as e:
                errors.append(f"{Path(path).name}: {e}")

        self._timing_undo.clear()
        self.btn_undo_timing.setEnabled(False)

        msg = f"Đã khôi phục {restored} file."
        if errors:
            msg += f"\nLỗi: {', '.join(errors)}"
        QMessageBox.information(self, "Hoàn tác", msg)
        self._log(f"[Thời gian] Hoàn tác: {restored} file khôi phục")

    def _on_inspector_tab_clicked(self, idx: int):
        self.inspector_tab_widget.setCurrentIndex(idx)
        for i, btn in enumerate(self.inspector_tab_buttons):
            btn.setChecked(i == idx)

    # ------------------------------------------------------------------
    # Edit Video Interactive Event Slots
    # ------------------------------------------------------------------

    def _on_mode_sub_clicked(self):
        self.btn_tab_sub.setChecked(True)
        self.btn_tab_video.setChecked(False)
        
        self.left_sub_container.setVisible(True)
        self.left_video_container.setVisible(False)
        self.middle_sub_container.setVisible(True)
        self.middle_video_container.setVisible(False)
        
        # Show SRT picker in Edit Sub mode
        self.pick_srt.setVisible(True)
        
        self.layer_tab_widget.setVisible(True)
        self.video_tab_widget.setVisible(False)
        
        # Show all 3 tabs: Phụ đề / Layer / Cài đặt xuất
        self.inspector_tab_buttons[0].setVisible(True)  # Phụ đề
        self.inspector_tab_widget.setTabVisible(0, True)  # tab_sub
        
        # Switch to Phụ đề tab
        self.inspector_tab_widget.setCurrentIndex(0)
        for i, btn in enumerate(self.inspector_tab_buttons):
            btn.setChecked(i == 0)
        
        self._scan_pairs()

    def _on_mode_video_clicked(self):
        self.btn_tab_sub.setChecked(False)
        self.btn_tab_video.setChecked(True)
        
        self.left_sub_container.setVisible(False)
        self.left_video_container.setVisible(True)
        self.middle_sub_container.setVisible(False)
        self.middle_video_container.setVisible(True)
        
        self.layer_tab_widget.setVisible(False)
        self.video_tab_widget.setVisible(True)
        
        # Hide SRT picker in Edit Video mode (video has no subtitles)
        self.pick_srt.setVisible(False)
        
        # Hide Phụ đề tab (only Layer / Cài đặt xuất)
        self.inspector_tab_buttons[0].setVisible(False)  # Phụ đề
        self.inspector_tab_widget.setTabVisible(0, False)  # tab_sub
        
        # Switch to Layer tab (index 1 in original, which is index 0 after hiding)
        self.inspector_tab_widget.setCurrentIndex(1)
        for i, btn in enumerate(self.inspector_tab_buttons):
            btn.setChecked(i == 1)
        
        self._on_video_layer_changed()
        self._scan_video_batch()

    def _on_video_selection_change(self, _val):
        self._scan_video_batch()

    def _scan_video_batch(self):
        src_files = self.pick_vid_src.selected_files()
        if not src_files and self.pick_vid_src.value():
            folder_path = self.pick_vid_src.value()
            if os.path.isdir(folder_path):
                exts = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
                src_files = []
                try:
                    for entry in os.scandir(folder_path):
                        if entry.is_file() and Path(entry.name).suffix.lower() in exts:
                            src_files.append(entry.path)
                except Exception:
                    pass
                src_files = sorted(list(set(src_files)))

        self._pairs = []
        self.vid_batch_table.blockSignals(True)
        try:
            self.vid_batch_table.setRowCount(0)
            
            if not src_files:
                self.lbl_vid_summary.setText("Tìm thấy 0 video")
                return

            unchecked_video_files = getattr(self, "_unchecked_video_files", set())
            for idx, file_path in enumerate(src_files):
                row = self.vid_batch_table.rowCount()
                self.vid_batch_table.insertRow(row)
                
                item_idx = QTableWidgetItem(str(idx + 1))
                item_idx.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item_idx.setFlags(item_idx.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item_idx.setData(Qt.ItemDataRole.UserRole, file_path)
                
                if file_path in unchecked_video_files:
                    item_idx.setCheckState(Qt.CheckState.Unchecked)
                else:
                    item_idx.setCheckState(Qt.CheckState.Checked)
                self.vid_batch_table.setItem(row, 0, item_idx)
                
                item_name = QTableWidgetItem(os.path.basename(file_path))
                item_name.setToolTip(file_path)
                self.vid_batch_table.setItem(row, 1, item_name)
                item_resolution = QTableWidgetItem("1280x720 (16:9)")
                item_resolution.setToolTip("1280x720 (16:9)")
                self.vid_batch_table.setItem(row, 2, item_resolution)
                
                item_status = QTableWidgetItem("Sẵn sàng")
                item_status.setToolTip("Sẵn sàng")
                item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item_status.setForeground(QColor("#2563eb"))
                self.vid_batch_table.setItem(row, 3, item_status)

                self._pairs.append(FilePair(
                    index=str(idx + 1),
                    audio_path=file_path,
                    srt_path="",
                    matched=True
                ))

            self.lbl_vid_summary.setText(f"Tìm thấy {len(src_files)} video — {len(src_files)} sẵn sàng")
        finally:
            self.vid_batch_table.blockSignals(False)

        if src_files:
            self.vid_batch_table.selectRow(0)

    def _on_video_batch_selection_changed(self):
        self._update_video_preview_frames()

    def _on_video_layer_changed(self):
        """Build layer configs and pass them to VideoLayoutPreview."""
        if not hasattr(self, "video_layout_preview") or not hasattr(self, "video_layer_widgets"):
            return
        
        configs = {}
        for idx, widget in enumerate(self.video_layer_widgets):
            layer_num = idx + 1
            configs[layer_num] = widget.get_config()
            active = configs[layer_num].enabled
            self.video_tab_widget.setTabText(idx, f"L{layer_num}")
            self.video_tab_widget.setTabToolTip(
                idx, f"Layer {layer_num}{' (đang bật)' if active else ''}"
            )

        self.video_layout_preview.set_configs(configs)
        self._update_video_preview_frames()
        self._save_timer.start(1000)

    def _update_video_preview_frames(self):
        if not hasattr(self, "video_layout_preview") or not hasattr(self, "video_layer_widgets"):
            return

        if not hasattr(self, "_video_frame_cache"):
            self._video_frame_cache = {}

        def get_cached_frame(path):
            if not path or not os.path.exists(path):
                return None
            if path in self._video_frame_cache:
                return self._video_frame_cache[path]
            
            lower_path = path.lower()
            if any(lower_path.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".bmp", ".webp"]):
                img = QImage(path)
                if not img.isNull():
                    self._add_frame_to_cache(path, img)
                    return self._video_frame_cache[path]
            
            # Asynchronous extraction for videos to prevent UI freezing
            if path in self.running_extractions:
                return None
            
            self.running_extractions.add(path)
            task = FrameExtractTask(path)
            task.signals.loaded.connect(self._on_frame_loaded)
            self.frame_pool.start(task)
            return None

        # 1. Update background frame
        bg_files = self.pick_vid_bg.selected_files()
        bg_img = None
        if bg_files:
            bg_img = get_cached_frame(bg_files[0])
        self.video_layout_preview.set_bg_image(bg_img)

        # 2. Update each of the 5 layers
        for idx, widget in enumerate(self.video_layer_widgets):
            layer_num = idx + 1
            cfg_obj = widget.get_config()
            
            layer_img = None
            if cfg_obj.enabled:
                src_idx = widget.cmb_source_type.currentIndex()
                if src_idx == 0:  # Video nền (Background video)
                    bg_files = self.pick_vid_bg.selected_files()
                    if bg_files:
                        layer_img = get_cached_frame(bg_files[0])
                elif src_idx == 1:  # Theo danh sách chạy (Video nguồn)
                    selected_ranges = self.vid_batch_table.selectedRanges()
                    if selected_ranges:
                        row = selected_ranges[0].topRow()
                        if 0 <= row < len(self._pairs):
                            batch_video_path = self._pairs[row].audio_path
                            layer_img = get_cached_frame(batch_video_path)
                else:  # File tĩnh (Static file)
                    static_path = widget.edit_path.text().strip()
                    if static_path:
                        layer_img = get_cached_frame(static_path)
            
            self.video_layout_preview.set_layer_image(layer_num, layer_img)
            widget.set_curve_histogram(layer_img)

    _FRAME_CACHE_MAX = 16
    _FRAME_CACHE_DIM = (960, 540)  # preview only; ~2 MB/frame vs ~3.7 MB at 720p

    def _add_frame_to_cache(self, path: str, img: QImage):
        if not img or img.isNull():
            return
        mw, mh = self._FRAME_CACHE_DIM
        if img.width() > mw or img.height() > mh:
            img = img.scaled(mw, mh, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._video_frame_cache[path] = img
        while len(self._video_frame_cache) > self._FRAME_CACHE_MAX:
            self._video_frame_cache.pop(next(iter(self._video_frame_cache)), None)

    def _on_frame_loaded(self, path: str, image: QImage):
        if path in self.running_extractions:
            self.running_extractions.remove(path)
        if image and not image.isNull():
            self._add_frame_to_cache(path, image)
            self._update_video_preview_frames()

    # ---- Shared preview-layer signal helpers ----

    @staticmethod
    def _set_spin_quiet(spin, value):
        spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(False)

    def _select_layer_tab(self, tab_widget, layers, index: int):
        if 1 <= index <= len(layers):
            tab_widget.setCurrentIndex(index - 1)

    def _apply_layer_moved(self, layers, index: int, t: int, b: int, l: int, r: int, on_changed):
        if not (1 <= index <= len(layers)):
            return
        widget = layers[index - 1]
        self._set_spin_quiet(widget.spn_margin_t, t)
        self._set_spin_quiet(widget.spn_margin_b, b)
        self._set_spin_quiet(widget.spn_margin_l, l)
        self._set_spin_quiet(widget.spn_margin_r, r)
        on_changed()

    def _apply_layer_resized(self, layers, index: int, scale_pct: int, on_changed):
        if not (1 <= index <= len(layers)):
            return
        widget = layers[index - 1]
        self._set_spin_quiet(widget.spn_size, scale_pct)
        on_changed()

    def _apply_layer_cropped(self, layers, index: int, t: int, b: int, l: int, r: int, on_changed):
        if not (1 <= index <= len(layers)):
            return
        widget = layers[index - 1]
        self._set_spin_quiet(widget.spn_crop_t, t)
        self._set_spin_quiet(widget.spn_crop_b, b)
        self._set_spin_quiet(widget.spn_crop_l, l)
        self._set_spin_quiet(widget.spn_crop_r, r)
        on_changed()

    def _apply_layer_color_picked(self, layers, layer_num: int, color_hex: str, on_changed):
        if 1 <= layer_num <= len(layers):
            layers[layer_num - 1].set_chroma_color(color_hex)
            on_changed()

    def _sync_preview_on_tab_change(self, preview_attr: str, layers_attr: str, index: int):
        if not hasattr(self, preview_attr) or not hasattr(self, layers_attr):
            return
        preview = getattr(self, preview_attr)
        layers = getattr(self, layers_attr)
        preview.select_layer(index + 1)
        if 0 <= index < len(layers):
            preview.set_crop_mode(layers[index].btn_crop_mode.isChecked())

    def _sync_layer_crop_toggle(self, tab_widget, layers, preview, enabled: bool, reset_text: str | None = None):
        sender_widget = self.sender()
        if not sender_widget:
            return
        current_idx = tab_widget.currentIndex()
        if 0 <= current_idx < len(layers) and sender_widget == layers[current_idx]:
            preview.set_crop_mode(enabled)
        for widget in layers:
            if widget != sender_widget and widget.btn_crop_mode.isChecked():
                widget.btn_crop_mode.blockSignals(True)
                widget.btn_crop_mode.setChecked(False)
                if reset_text is not None:
                    widget.btn_crop_mode.setText(reset_text)
                widget.btn_crop_mode.blockSignals(False)

    # ---- Video layer preview slots ----

    def _on_preview_layer_selected(self, index: int):
        self._select_layer_tab(self.video_tab_widget, self.video_layer_widgets, index)

    def _on_preview_layer_moved(self, index: int, t: int, b: int, l: int, r: int):
        self._apply_layer_moved(self.video_layer_widgets, index, t, b, l, r, self._on_video_layer_changed)

    def _on_preview_layer_resized(self, index: int, scale_pct: int):
        self._apply_layer_resized(self.video_layer_widgets, index, scale_pct, self._on_video_layer_changed)

    def _on_preview_layer_cropped(self, index: int, t: int, b: int, l: int, r: int):
        self._apply_layer_cropped(self.video_layer_widgets, index, t, b, l, r, self._on_video_layer_changed)

    def _on_eyedropper_requested(self, layer_num: int):
        if hasattr(self, "video_layout_preview"):
            self.video_layout_preview.select_layer(layer_num)
            self.video_layout_preview.set_eyedropper_active(True)

    def _on_preview_color_picked(self, layer_num: int, color_hex: str):
        self._apply_layer_color_picked(self.video_layer_widgets, layer_num, color_hex, self._on_video_layer_changed)

    def _on_video_tab_changed(self, index: int):
        self._sync_preview_on_tab_change("video_layout_preview", "video_layer_widgets", index)

    def _on_video_layer_crop_toggled(self, enabled: bool):
        self._sync_layer_crop_toggle(
            self.video_tab_widget, self.video_layer_widgets, self.video_layout_preview,
            enabled, reset_text="✂  Bật Crop Mode",
        )

    # ---- Logo layer preview slots ----

    def _on_logo_eyedropper_requested(self, layer_num: int):
        if hasattr(self, "preview_widget"):
            self.preview_widget.set_eyedropper_active(layer_num)

    def _on_logo_preview_color_picked(self, layer_num: int, color_hex: str):
        self._apply_layer_color_picked(self.logo_layers, layer_num, color_hex, self._on_logo_settings_changed)

    def _on_logo_preview_layer_selected(self, index: int):
        self._select_layer_tab(self.layer_tab_widget, self.logo_layers, index)

    def _on_logo_preview_layer_moved(self, index: int, t: int, b: int, l: int, r: int):
        self._apply_layer_moved(self.logo_layers, index, t, b, l, r, self._on_logo_settings_changed)

    def _on_logo_preview_layer_resized(self, index: int, scale_pct: int):
        self._apply_layer_resized(self.logo_layers, index, scale_pct, self._on_logo_settings_changed)

    def _on_logo_preview_layer_cropped(self, index: int, t: int, b: int, l: int, r: int):
        self._apply_layer_cropped(self.logo_layers, index, t, b, l, r, self._on_logo_settings_changed)

    def _on_logo_tab_changed(self, index: int):
        self._sync_preview_on_tab_change("preview_widget", "logo_layers", index)

    def _on_logo_crop_toggled(self, enabled: bool):
        self._sync_layer_crop_toggle(
            self.layer_tab_widget, self.logo_layers, self.preview_widget, enabled,
        )

    def _pair_select_all(self):
        for row in range(self.pair_table.rowCount()):
            item = self.pair_table.item(row, 0)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Checked)

    def _pair_deselect_all(self):
        for row in range(self.pair_table.rowCount()):
            item = self.pair_table.item(row, 0)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _vid_select_all(self):
        for row in range(self.vid_batch_table.rowCount()):
            item = self.vid_batch_table.item(row, 0)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Checked)

    def _vid_deselect_all(self):
        for row in range(self.vid_batch_table.rowCount()):
            item = self.vid_batch_table.item(row, 0)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _on_table_item_changed(self, item):
        if item.column() != 0:
            return
        table = self.sender()
        if not table:
            return
        table.blockSignals(True)
        try:
            selected_ranges = table.selectedRanges()
            if selected_ranges:
                state = item.checkState()
                clicked_row = item.row()
                
                # Check if clicked row is part of the selected ranges
                in_selection = False
                for r in selected_ranges:
                    if r.topRow() <= clicked_row <= r.bottomRow():
                        in_selection = True
                        break
                        
                if in_selection:
                    for r in selected_ranges:
                        for row in range(r.topRow(), r.bottomRow() + 1):
                            idx_item = table.item(row, 0)
                            if idx_item and idx_item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                                idx_item.setCheckState(state)
        finally:
            table.blockSignals(False)

    def closeEvent(self, event):
        self._save_timer.stop()
        self._save_settings()
        self.frame_pool.clear()
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(3000)
        event.accept()
