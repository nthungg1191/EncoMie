"""
Widget for configuring a single video layer (1 of 5) in the Edit Video tab.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QFrame, QLineEdit, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import pyqtSignal, Qt
from pathlib import Path
import os

from core.video_processor import ImageLayerConfig
from ui.collapsible_section import CollapsibleSection

class VideoLayerConfigWidget(QWidget):
    MAX_HEIGHT = 380  # Fixed max height with scrollbar

    changed = pyqtSignal()
    cropModeToggled = pyqtSignal(bool)
    eyedropperRequested = pyqtSignal(int)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.chroma_key_color = "#00FF00"
        self._init_ui()


    def _init_ui(self):
        # Outer wrapper with scroll area
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # AsNeeded (not AlwaysOff): if the panel gets narrower than the content can
        # reasonably shrink, show a scrollbar instead of silently clipping widgets.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        # Inner content widget
        content = QWidget()
        # Floor width: below this the scroll area shows a horizontal scrollbar
        # instead of squashing/clipping the group-box rows.
        content.setMinimumWidth(320)
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(10, 10, 10, 10)
        content_lay.setSpacing(8)

        # Row 1: Active switch & Source Picker
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        
        self.chk_enabled = QCheckBox("Kích hoạt Layer")
        self.chk_enabled.setStyleSheet("font-size: 11px; font-weight: bold;")
        self.chk_enabled.stateChanged.connect(self._on_changed)
        row1.addWidget(self.chk_enabled)

        # Source type selector (Background, Batch or static file)
        self.cmb_source_type = QComboBox()
        self.cmb_source_type.addItems([
            "Video nền (Background video)",
            "Theo danh sách chạy (Video nguồn)",
            "File cố định (Static file...)"
        ])
        self.cmb_source_type.setStyleSheet("font-size: 11px;")
        self.cmb_source_type.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_source_type.setMinimumContentsLength(8)
        self.cmb_source_type.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.cmb_source_type.currentIndexChanged.connect(self._on_source_type_changed)
        row1.addWidget(self.cmb_source_type, 1)
        content_lay.addLayout(row1)

        # Static file selector row (visible only if Static file is selected)
        self.static_file_frame = QFrame()
        self.static_file_frame.setFrameShape(QFrame.Shape.NoFrame)
        static_lay = QHBoxLayout(self.static_file_frame)
        static_lay.setContentsMargins(0, 0, 0, 0)
        static_lay.setSpacing(6)

        self.lbl_path = QLabel("Đường dẫn:")
        self.lbl_path.setStyleSheet("font-size: 11px;")
        self.lbl_path.setFixedWidth(60)
        static_lay.addWidget(self.lbl_path)

        self.edit_path = QLineEdit()
        self.edit_path.setReadOnly(True)
        self.edit_path.setPlaceholderText("Chọn file video/ảnh...")
        self.edit_path.setStyleSheet("font-size: 11px;")
        static_lay.addWidget(self.edit_path, 1)

        self.btn_browse = QPushButton("Chọn…")
        self.btn_browse.setFixedWidth(55)
        self.btn_browse.setStyleSheet("font-size: 11px;")
        self.btn_browse.clicked.connect(self._browse_static_file)
        static_lay.addWidget(self.btn_browse)

        content_lay.addWidget(self.static_file_frame)
        self.static_file_frame.setVisible(False) # Default is Batch file

        # ------------------------------------------------------------------
        # Below: collapsible sections (accordion). Several can be open at once
        # (click a header to toggle just that one) instead of 7 always-expanded
        # group boxes, so the common case - checking what a layer does without
        # scrolling past everything - fits in one glance. See "So Sánh Bảng
        # Layer" design demo for the reasoning behind this layout.
        # ------------------------------------------------------------------

        # Section 1: Vị trí & Kích thước - open by default, the most frequently
        # touched controls for any layer.
        self.sec_transform = CollapsibleSection("Vị trí & Kích thước", open_=True)
        t_lay = self.sec_transform.body_layout

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        pos_lbl = QLabel("Vị trí đè:")
        pos_lbl.setStyleSheet("font-size: 11px;")
        pos_lbl.setFixedWidth(60)
        row2.addWidget(pos_lbl)

        self.cmb_pos = QComboBox()
        self.cmb_pos.addItems([
            "Ở giữa (Center)",
            "Góc dưới - Phải (Bottom-Right)",
            "Góc dưới - Trái (Bottom-Left)",
            "Góc trên - Phải (Top-Right)",
            "Góc trên - Trái (Top-Left)"
        ])
        self.cmb_pos.setStyleSheet("font-size: 11px;")
        self.cmb_pos.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_pos.setMinimumContentsLength(8)
        self.cmb_pos.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.cmb_pos.currentIndexChanged.connect(self._on_pos_changed)
        row2.addWidget(self.cmb_pos, 1)
        t_lay.addLayout(row2)

        row3 = QGridLayout()
        row3.setSpacing(10)

        sz_lbl = QLabel("Cỡ (%):")
        sz_lbl.setStyleSheet("font-size: 11px;")
        row3.addWidget(sz_lbl, 0, 0)

        self.spn_size = QSpinBox()
        self.spn_size.setRange(10, 150)
        self.spn_size.setValue(30 if self.index == 1 else 15)
        self.spn_size.setStyleSheet("font-size: 11px;")
        self.spn_size.valueChanged.connect(self._on_changed)
        row3.addWidget(self.spn_size, 0, 1)

        op_lbl = QLabel("Độ mờ (%):")
        op_lbl.setStyleSheet("font-size: 11px;")
        row3.addWidget(op_lbl, 0, 2)

        self.spn_opacity = QSpinBox()
        self.spn_opacity.setRange(10, 100)
        self.spn_opacity.setValue(100)
        self.spn_opacity.setSingleStep(5)
        self.spn_opacity.setStyleSheet("font-size: 11px;")
        self.spn_opacity.valueChanged.connect(self._on_changed)
        row3.addWidget(self.spn_opacity, 0, 3)

        row3.setColumnStretch(1, 1)
        row3.setColumnStretch(3, 1)
        t_lay.addLayout(row3)

        # Tốc độ chạy layer (chỉ video, có thể ẩn) & Độ nhòe (Blur, luôn hiện
        # kể cả layer ảnh tĩnh) - cùng 1 hàng, 2 cột responsive.
        row_speed_grid = QGridLayout()
        row_speed_grid.setContentsMargins(0, 0, 0, 0)
        row_speed_grid.setSpacing(10)

        # Tốc độ chỉ áp dụng cho video nên gói riêng trong 1 widget để ẩn/hiện
        # mà không kéo theo ô Blur (áp dụng được cho cả layer ảnh tĩnh).
        self.row_speed_widget = QWidget()
        speed_pair_lay = QHBoxLayout(self.row_speed_widget)
        speed_pair_lay.setContentsMargins(0, 0, 0, 0)
        speed_pair_lay.setSpacing(10)

        speed_lbl = QLabel("Tốc độ layer (%):")
        speed_lbl.setStyleSheet("font-size: 11px;")
        speed_pair_lay.addWidget(speed_lbl)

        self.spn_speed = QSpinBox()
        self.spn_speed.setRange(10, 300)
        self.spn_speed.setValue(100)
        self.spn_speed.setSuffix("%")
        self.spn_speed.setStyleSheet("font-size: 11px;")
        self.spn_speed.valueChanged.connect(self._on_changed)
        speed_pair_lay.addWidget(self.spn_speed, 1)

        row_speed_grid.addWidget(self.row_speed_widget, 0, 0, 1, 2)

        blur_lbl = QLabel("Độ nhòe (Blur):")
        blur_lbl.setStyleSheet("font-size: 11px;")
        row_speed_grid.addWidget(blur_lbl, 0, 2)

        self.spn_blur = QDoubleSpinBox()
        self.spn_blur.setRange(0.0, 20.0)
        self.spn_blur.setSingleStep(0.5)
        self.spn_blur.setValue(0.0)
        self.spn_blur.setStyleSheet("font-size: 11px;")
        self.spn_blur.valueChanged.connect(self._on_changed)
        row_speed_grid.addWidget(self.spn_blur, 0, 3)

        row_speed_grid.setColumnStretch(1, 1)
        row_speed_grid.setColumnStretch(3, 1)

        t_lay.addLayout(row_speed_grid)
        content_lay.addWidget(self.sec_transform)

        # Section 2: Khoảng lề (Margin) - open by default, baseline positioning.
        self.sec_margin = CollapsibleSection("Khoảng lề (Margin - px)", open_=True)
        margin_lay = QGridLayout()
        margin_lay.setContentsMargins(0, 0, 0, 0)
        margin_lay.setSpacing(6)

        margin_lay.addWidget(QLabel("Trên:"), 0, 0)
        self.spn_margin_t = QSpinBox()
        self.spn_margin_t.setRange(0, 1000)
        self.spn_margin_t.setValue(60 if self.index == 1 else 145)
        self.spn_margin_t.valueChanged.connect(self._on_changed)
        margin_lay.addWidget(self.spn_margin_t, 0, 1)

        margin_lay.addWidget(QLabel("Dưới:"), 0, 2)
        self.spn_margin_b = QSpinBox()
        self.spn_margin_b.setRange(0, 1000)
        self.spn_margin_b.setValue(60 if self.index == 1 else 20)
        self.spn_margin_b.valueChanged.connect(self._on_changed)
        margin_lay.addWidget(self.spn_margin_b, 0, 3)

        margin_lay.addWidget(QLabel("Trái:"), 1, 0)
        self.spn_margin_l = QSpinBox()
        self.spn_margin_l.setRange(0, 1000)
        self.spn_margin_l.setValue(140 if self.index == 1 else 320)
        self.spn_margin_l.valueChanged.connect(self._on_changed)
        margin_lay.addWidget(self.spn_margin_l, 1, 1)

        margin_lay.addWidget(QLabel("Phải:"), 1, 2)
        self.spn_margin_r = QSpinBox()
        self.spn_margin_r.setRange(0, 1000)
        self.spn_margin_r.setValue(140 if self.index == 1 else 20)
        self.spn_margin_r.valueChanged.connect(self._on_changed)
        margin_lay.addWidget(self.spn_margin_r, 1, 3)

        self.sec_margin.body_layout.addLayout(margin_lay)
        content_lay.addWidget(self.sec_margin)

        # Section 3: Cắt cúp (Crop) - collapsed by default.
        self.sec_crop = CollapsibleSection("Cắt cúp (Crop)")
        crop_lay = QGridLayout()
        crop_lay.setContentsMargins(0, 0, 0, 0)
        crop_lay.setSpacing(6)

        self.btn_crop_mode = QPushButton("✂  Bật Crop Mode")
        self.btn_crop_mode.setCheckable(True)
        self.btn_crop_mode.setStyleSheet(
            "QPushButton { background: #fef3c7; color: #d97706; border: 1px solid #f59e0b; "
            "padding: 4px; border-radius: 4px; font-size: 11px; font-weight: bold; }"
            "QPushButton:checked { background: #f59e0b; color: #ffffff; }"
        )
        self.btn_crop_mode.toggled.connect(self._on_crop_mode_toggled)
        crop_lay.addWidget(self.btn_crop_mode, 0, 0, 1, 4)

        crop_lay.addWidget(QLabel("Cắt Trên:"), 1, 0)
        self.spn_crop_t = QSpinBox()
        self.spn_crop_t.setRange(0, 500)
        self.spn_crop_t.setValue(0)
        self.spn_crop_t.valueChanged.connect(self._on_changed)
        crop_lay.addWidget(self.spn_crop_t, 1, 1)

        crop_lay.addWidget(QLabel("Cắt Dưới:"), 1, 2)
        self.spn_crop_b = QSpinBox()
        self.spn_crop_b.setRange(0, 500)
        self.spn_crop_b.setValue(0)
        self.spn_crop_b.valueChanged.connect(self._on_changed)
        crop_lay.addWidget(self.spn_crop_b, 1, 3)

        crop_lay.addWidget(QLabel("Cắt Trái:"), 2, 0)
        self.spn_crop_l = QSpinBox()
        self.spn_crop_l.setRange(0, 500)
        self.spn_crop_l.setValue(0)
        self.spn_crop_l.valueChanged.connect(self._on_changed)
        crop_lay.addWidget(self.spn_crop_l, 2, 1)

        crop_lay.addWidget(QLabel("Cắt Phải:"), 2, 2)
        self.spn_crop_r = QSpinBox()
        self.spn_crop_r.setRange(0, 500)
        self.spn_crop_r.setValue(0)
        self.spn_crop_r.valueChanged.connect(self._on_changed)
        crop_lay.addWidget(self.spn_crop_r, 2, 3)

        self.sec_crop.body_layout.addLayout(crop_lay)
        content_lay.addWidget(self.sec_crop)

        # Section 4: Chroma Key - collapsed by default.
        self.sec_chroma = CollapsibleSection("Chroma Key")

        self.chk_chroma_enabled = QCheckBox("Kích hoạt khử nền xanh")
        self.chk_chroma_enabled.setStyleSheet("font-size: 11px;")
        self.chk_chroma_enabled.stateChanged.connect(self._on_chroma_enabled_changed)
        self.sec_chroma.body_layout.addWidget(self.chk_chroma_enabled)

        self.chroma_params_frame = QWidget()
        chroma_params_lay = QGridLayout(self.chroma_params_frame)
        chroma_params_lay.setContentsMargins(0, 0, 0, 0)
        chroma_params_lay.setSpacing(6)

        chroma_params_lay.addWidget(QLabel("Độ nhạy:"), 0, 0)
        self.spn_chroma_sim = QDoubleSpinBox()
        self.spn_chroma_sim.setRange(0.01, 1.00)
        self.spn_chroma_sim.setSingleStep(0.01)
        self.spn_chroma_sim.setValue(0.38)
        self.spn_chroma_sim.setStyleSheet("font-size: 11px;")
        self.spn_chroma_sim.valueChanged.connect(self._on_changed)
        chroma_params_lay.addWidget(self.spn_chroma_sim, 0, 1)

        chroma_params_lay.addWidget(QLabel("Độ mềm:"), 0, 2)
        self.spn_chroma_blend = QDoubleSpinBox()
        self.spn_chroma_blend.setRange(0.00, 1.00)
        self.spn_chroma_blend.setSingleStep(0.01)
        self.spn_chroma_blend.setValue(0.08)
        self.spn_chroma_blend.setStyleSheet("font-size: 11px;")
        self.spn_chroma_blend.valueChanged.connect(self._on_changed)
        chroma_params_lay.addWidget(self.spn_chroma_blend, 0, 3)

        chroma_params_lay.addWidget(QLabel("Màu khử:"), 1, 0)
        self.btn_chroma_color = QPushButton()
        self.btn_chroma_color.setFixedSize(24, 24)
        self.btn_chroma_color.setStyleSheet(f"background-color: {self.chroma_key_color}; border: 1px solid #cccccc; border-radius: 4px;")
        self.btn_chroma_color.clicked.connect(self._on_color_picker_clicked)
        chroma_params_lay.addWidget(self.btn_chroma_color, 1, 1)

        self.btn_eyedropper = QPushButton("Hút màu từ ảnh (Eyedropper)")
        self.btn_eyedropper.setStyleSheet("font-size: 11px;")
        self.btn_eyedropper.clicked.connect(self._on_eyedropper_clicked)
        chroma_params_lay.addWidget(self.btn_eyedropper, 1, 2, 1, 2)

        chroma_params_lay.addWidget(QLabel("Khử tràn màu:"), 2, 0)
        self.spn_chroma_spill = QDoubleSpinBox()
        self.spn_chroma_spill.setRange(0.00, 1.00)
        self.spn_chroma_spill.setSingleStep(0.05)
        self.spn_chroma_spill.setValue(0.00)
        self.spn_chroma_spill.setStyleSheet("font-size: 11px;")
        self.spn_chroma_spill.valueChanged.connect(self._on_changed)
        chroma_params_lay.addWidget(self.spn_chroma_spill, 2, 1)

        self.sec_chroma.body_layout.addWidget(self.chroma_params_frame)
        self.chroma_params_frame.setVisible(False)
        content_lay.addWidget(self.sec_chroma)

        # Section 5: Luma Key (remove background by brightness, not colour) -
        # the Premiere-style companion to Chroma Key above; only plain numeric
        # controls since there's no colour to pick. Mutually exclusive with
        # Chroma Key (see the toggle handlers). Collapsed by default.
        self.sec_luma = CollapsibleSection("Luma Key")

        self.chk_luma_enabled = QCheckBox("Kích hoạt Luma Key")
        self.chk_luma_enabled.setStyleSheet("font-size: 11px;")
        self.chk_luma_enabled.stateChanged.connect(self._on_luma_enabled_changed)
        self.sec_luma.body_layout.addWidget(self.chk_luma_enabled)

        self.luma_params_frame = QWidget()
        luma_params_lay = QGridLayout(self.luma_params_frame)
        luma_params_lay.setContentsMargins(0, 0, 0, 0)
        luma_params_lay.setSpacing(6)

        # Threshold: where on the black<->white range keying happens. Low =
        # remove dark/black backgrounds (most common), high = remove white.
        # Tolerance: width of the band around threshold that's keyed out.
        # Softness: width of the soft alpha ramp beyond that band's edge.
        luma_params_lay.addWidget(QLabel("Ngưỡng:"), 0, 0)
        self.spn_luma_threshold = QDoubleSpinBox()
        self.spn_luma_threshold.setRange(0.00, 1.00)
        self.spn_luma_threshold.setSingleStep(0.01)
        self.spn_luma_threshold.setValue(0.10)
        self.spn_luma_threshold.setToolTip("0 = xóa nền tối/đen  ·  1 = xóa nền sáng/trắng")
        self.spn_luma_threshold.setStyleSheet("font-size: 11px;")
        self.spn_luma_threshold.valueChanged.connect(self._on_changed)
        luma_params_lay.addWidget(self.spn_luma_threshold, 0, 1)

        luma_params_lay.addWidget(QLabel("Dung sai:"), 0, 2)
        self.spn_luma_tolerance = QDoubleSpinBox()
        self.spn_luma_tolerance.setRange(0.00, 1.00)
        self.spn_luma_tolerance.setSingleStep(0.01)
        self.spn_luma_tolerance.setValue(0.05)
        self.spn_luma_tolerance.setToolTip("Vùng độ sáng quanh Ngưỡng cũng bị xóa")
        self.spn_luma_tolerance.setStyleSheet("font-size: 11px;")
        self.spn_luma_tolerance.valueChanged.connect(self._on_changed)
        luma_params_lay.addWidget(self.spn_luma_tolerance, 0, 3)

        luma_params_lay.addWidget(QLabel("Độ mềm viền:"), 1, 0)
        self.spn_luma_softness = QDoubleSpinBox()
        self.spn_luma_softness.setRange(0.00, 1.00)
        self.spn_luma_softness.setSingleStep(0.01)
        self.spn_luma_softness.setValue(0.05)
        self.spn_luma_softness.setStyleSheet("font-size: 11px;")
        self.spn_luma_softness.valueChanged.connect(self._on_changed)
        luma_params_lay.addWidget(self.spn_luma_softness, 1, 1)

        self.sec_luma.body_layout.addWidget(self.luma_params_frame)
        self.luma_params_frame.setVisible(False)
        content_lay.addWidget(self.sec_luma)

        # Section 6: Curves (Pro) - collapsed by default.
        self.sec_curves = CollapsibleSection("🎨  Curves")
        from ui.color_grade_panel import ColorGradePanel
        self.color_panel = ColorGradePanel()
        self.color_panel.changed.connect(self._on_changed)
        self.color_panel.set_locked(True)  # unlocked when a Pro licence is confirmed
        self.sec_curves.body_layout.addWidget(self.color_panel)
        content_lay.addWidget(self.sec_curves)

        content_lay.addStretch(1)

        # Keep every number field compact so the 2-column grid rows fit a narrow
        # panel without forcing a horizontal scrollbar.
        for _sb in content.findChildren((QSpinBox, QDoubleSpinBox)):
            _sb.setMinimumWidth(0)
            _sb.setMaximumWidth(90)
            _sb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Set scroll area widget
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Default states: Layer 1 and 2 are active on wireframe demo
        if self.index in (1, 2):
            self.chk_enabled.setChecked(True)
        else:
            self.chk_enabled.setChecked(False)

        # Initialize mock values for Layer 2
        if self.index == 2:
            self.cmb_source_type.setCurrentIndex(1) # Static file
            self.edit_path.setText("logo.png")
            self.cmb_pos.setCurrentIndex(1) # Bottom-Right

        self._update_speed_visibility()
        self._refresh_section_badges()

    def _on_source_type_changed(self, idx: int):
        self.static_file_frame.setVisible(idx == 2)
        self._update_speed_visibility()
        self._on_changed()

    def _browse_static_file(self):
        from PyQt6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file video/ảnh phủ đè",
            "",
            "Media files (*.png *.jpg *.jpeg *.bmp *.mp4 *.mov *.avi *.mkv);;All files (*.*)"
        )
        if file_path:
            self.edit_path.setText(file_path)
            self._update_speed_visibility()
            self._on_changed()

    def _on_crop_mode_toggled(self, checked: bool):
        if checked:
            self.btn_crop_mode.setText("✓  Đang Crop (Tắt)")
        else:
            self.btn_crop_mode.setText("✂  Bật Crop Mode")
        self.cropModeToggled.emit(checked)
        self._refresh_section_badges()

    def set_crop_mode_checked(self, checked: bool):
        """Restore the crop-mode toggle without re-emitting cropModeToggled
        (preview sync is done by the tab-change handler on load)."""
        checked = bool(checked)
        self.btn_crop_mode.blockSignals(True)
        self.btn_crop_mode.setChecked(checked)
        self.btn_crop_mode.setText("✓  Đang Crop (Tắt)" if checked else "✂  Bật Crop Mode")
        self.btn_crop_mode.blockSignals(False)

    def _on_chroma_enabled_changed(self, state: int):
        # In PyQt6, check state can be an int or CheckState
        enabled = (state == 2) or (state == Qt.CheckState.Checked.value) or (hasattr(Qt.CheckState, "Checked") and state == Qt.CheckState.Checked)
        self.chroma_params_frame.setVisible(enabled)
        # Chroma and Luma key both answer "what makes this layer transparent?" -
        # having both on at once is ambiguous, so picking one turns the other off.
        if enabled and self.chk_luma_enabled.isChecked():
            self.chk_luma_enabled.setChecked(False)
        if enabled:
            self.sec_chroma.set_open(True)
        self._on_changed()

    def _on_luma_enabled_changed(self, state: int):
        enabled = (state == 2) or (state == Qt.CheckState.Checked.value) or (hasattr(Qt.CheckState, "Checked") and state == Qt.CheckState.Checked)
        self.luma_params_frame.setVisible(enabled)
        if enabled and self.chk_chroma_enabled.isChecked():
            self.chk_chroma_enabled.setChecked(False)
        if enabled:
            self.sec_luma.set_open(True)
        self._on_changed()

    def _update_speed_visibility(self):
        idx = self.cmb_source_type.currentIndex()
        if idx in (0, 1):
            self.row_speed_widget.setVisible(True)
        else:
            path = self.edit_path.text().lower()
            is_video = any(path.endswith(ext) for ext in [".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"])
            self.row_speed_widget.setVisible(is_video)

    def _on_changed(self):
        self._refresh_section_badges()
        self.changed.emit()

    def _refresh_section_badges(self):
        """Keep each collapsed section's header readable at a glance: a status
        badge for on/off toggles, a value summary for the always-on ones."""
        if not hasattr(self, "sec_curves"):
            return  # called mid-construction, before every section exists yet

        self.sec_transform.set_subtitle(f"{self.spn_size.value()}% · {self.spn_opacity.value()}%")
        self.sec_margin.set_subtitle(
            f"{self.spn_margin_t.value()}·{self.spn_margin_b.value()}·"
            f"{self.spn_margin_l.value()}·{self.spn_margin_r.value()}"
        )

        crop_active = any(v.value() > 0 for v in
                          (self.spn_crop_t, self.spn_crop_b, self.spn_crop_l, self.spn_crop_r))
        if self.btn_crop_mode.isChecked():
            self.sec_crop.set_badge("ĐANG CHỈNH", "warn")
        elif crop_active:
            self.sec_crop.set_badge("BẬT", "on")
        else:
            self.sec_crop.set_badge("TẮT", "off")

        chroma_on = self.chk_chroma_enabled.isChecked()
        self.sec_chroma.set_badge("BẬT" if chroma_on else "TẮT", "on" if chroma_on else "off")

        luma_on = self.chk_luma_enabled.isChecked()
        self.sec_luma.set_badge("BẬT" if luma_on else "TẮT", "on" if luma_on else "off")

        if self.color_panel.is_locked():
            self.sec_curves.set_badge("PRO", "pro")
        else:
            cg = self.color_panel.get_config()
            active = cg.enabled and cg.is_active()
            self.sec_curves.set_badge("BẬT" if active else "TẮT", "on" if active else "off")

    def get_config(self) -> ImageLayerConfig:
        """Returns the configuration parsed from widgets."""
        idx = self.cmb_source_type.currentIndex()
        if idx == 0:
            path_val = "Video nền"
        elif idx == 1:
            path_val = "Theo danh sách chạy"
        else:
            path_val = self.edit_path.text()
            
        # Mapping index to ImageLayerConfig position:
        # Combo positions: 0: Center, 1: BR, 2: BL, 3: TR, 4: TL
        # Config positions: 0: BR, 1: BL, 2: TR, 3: TL, 4: TC (Center)
        combo_to_config = {0: 4, 1: 0, 2: 1, 3: 2, 4: 3}
        pos_val = combo_to_config.get(self.cmb_pos.currentIndex(), 4)

        cfg_obj = ImageLayerConfig(
            enabled=self.chk_enabled.isChecked(),
            path=path_val,
            position=pos_val,
            size=self.spn_size.value(),
            opacity=self.spn_opacity.value() / 100.0,
            margin_t=self.spn_margin_t.value(),
            margin_b=self.spn_margin_b.value(),
            margin_l=self.spn_margin_l.value(),
            margin_r=self.spn_margin_r.value()
        )
        # Extend config dynamically with crop/radius
        cfg_obj.crop_t = self.spn_crop_t.value()
        cfg_obj.crop_b = self.spn_crop_b.value()
        cfg_obj.crop_l = self.spn_crop_l.value()
        cfg_obj.crop_r = self.spn_crop_r.value()
        cfg_obj.radius = 0
        cfg_obj.speed = self.spn_speed.value()
        cfg_obj.chroma_key_enabled = self.chk_chroma_enabled.isChecked()
        cfg_obj.chroma_key_similarity = self.spn_chroma_sim.value()
        cfg_obj.chroma_key_blend = self.spn_chroma_blend.value()
        cfg_obj.chroma_key_color = self.chroma_key_color
        cfg_obj.chroma_key_spill = self.spn_chroma_spill.value()
        cfg_obj.luma_key_enabled = self.chk_luma_enabled.isChecked()
        cfg_obj.luma_key_threshold = self.spn_luma_threshold.value()
        cfg_obj.luma_key_tolerance = self.spn_luma_tolerance.value()
        cfg_obj.luma_key_softness = self.spn_luma_softness.value()
        cfg_obj.blur = self.spn_blur.value()
        cfg_obj.color_grade = self.color_panel.get_config()
        cfg_obj.crop_mode = self.btn_crop_mode.isChecked()
        cfg_obj.source_type = idx # Save index
        return cfg_obj

    def set_color_locked(self, locked: bool):
        self.color_panel.set_locked(locked)
        self._refresh_section_badges()

    def set_curve_histogram(self, img):
        self.color_panel.set_histogram_image(img)

    def set_config(self, cfg_obj: ImageLayerConfig):
        """Populates the widget values from a config object."""
        self.chk_enabled.setChecked(cfg_obj.enabled)
        
        idx = getattr(cfg_obj, "source_type", -1)
        if idx == -1:
            if cfg_obj.path == "Video nền":
                idx = 0
            elif cfg_obj.path == "Theo danh sách chạy" or not cfg_obj.path:
                idx = 1
            else:
                idx = 2
                
        self.cmb_source_type.setCurrentIndex(idx)
        if idx == 2:
            self.edit_path.setText(cfg_obj.path)
        else:
            self.edit_path.clear()

        # Config to Combo position mapping
        config_to_combo = {4: 0, 0: 1, 1: 2, 2: 3, 3: 4}
        self.cmb_pos.blockSignals(True)
        self.cmb_pos.setCurrentIndex(config_to_combo.get(cfg_obj.position, 0))
        self.cmb_pos.blockSignals(False)

        self.spn_size.setValue(cfg_obj.size)
        self.spn_opacity.setValue(int(getattr(cfg_obj, "opacity", 1.0) * 100))
        self.spn_blur.setValue(getattr(cfg_obj, "blur", 0.0))
        self.spn_margin_t.setValue(cfg_obj.margin_t)
        self.spn_margin_b.setValue(cfg_obj.margin_b)
        self.spn_margin_l.setValue(cfg_obj.margin_l)
        self.spn_margin_r.setValue(cfg_obj.margin_r)

        self.spn_crop_t.setValue(getattr(cfg_obj, "crop_t", 0))
        self.spn_crop_b.setValue(getattr(cfg_obj, "crop_b", 0))
        self.spn_crop_l.setValue(getattr(cfg_obj, "crop_l", 0))
        self.spn_crop_r.setValue(getattr(cfg_obj, "crop_r", 0))
        self.set_crop_mode_checked(getattr(cfg_obj, "crop_mode", False))
        self.spn_speed.setValue(getattr(cfg_obj, "speed", 100))
        
        self.chk_chroma_enabled.setChecked(getattr(cfg_obj, "chroma_key_enabled", False))
        self.spn_chroma_sim.setValue(getattr(cfg_obj, "chroma_key_similarity", 0.38))
        self.spn_chroma_blend.setValue(getattr(cfg_obj, "chroma_key_blend", 0.08))
        self.set_chroma_color(getattr(cfg_obj, "chroma_key_color", "#00FF00"))
        self.spn_chroma_spill.setValue(getattr(cfg_obj, "chroma_key_spill", 0.0))
        self.chroma_params_frame.setVisible(self.chk_chroma_enabled.isChecked())

        self.chk_luma_enabled.setChecked(getattr(cfg_obj, "luma_key_enabled", False))
        self.spn_luma_threshold.setValue(getattr(cfg_obj, "luma_key_threshold", 0.10))
        self.spn_luma_tolerance.setValue(getattr(cfg_obj, "luma_key_tolerance", 0.05))
        self.spn_luma_softness.setValue(getattr(cfg_obj, "luma_key_softness", 0.05))
        self.luma_params_frame.setVisible(self.chk_luma_enabled.isChecked())

        self.color_panel.set_config(getattr(cfg_obj, "color_grade", None))

        self._update_speed_visibility()
        self._refresh_section_badges()

    def set_chroma_color(self, color_hex: str):
        self.chroma_key_color = color_hex
        if hasattr(self, "btn_chroma_color"):
            self.btn_chroma_color.setStyleSheet(
                f"background-color: {color_hex}; border: 1px solid #cccccc; border-radius: 4px;"
            )

    def _on_color_picker_clicked(self):
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor
        color = QColorDialog.getColor(QColor(self.chroma_key_color), self, "Chọn màu cần khử")
        if color.isValid():
            self.set_chroma_color(color.name())
            self._on_changed()

    def _on_eyedropper_clicked(self):
        self.eyedropperRequested.emit(self.index)

    def _on_pos_changed(self, index: int):
        # Snap margins when position changes in UI
        self.spn_margin_t.blockSignals(True)
        self.spn_margin_b.blockSignals(True)
        self.spn_margin_l.blockSignals(True)
        self.spn_margin_r.blockSignals(True)
        
        if index == 0: # Center
            self.spn_margin_t.setValue(0)
            self.spn_margin_b.setValue(0)
            self.spn_margin_l.setValue(0)
            self.spn_margin_r.setValue(0)
        elif index == 1: # BR
            self.spn_margin_t.setValue(0)
            self.spn_margin_b.setValue(20)
            self.spn_margin_l.setValue(0)
            self.spn_margin_r.setValue(20)
        elif index == 2: # BL
            self.spn_margin_t.setValue(0)
            self.spn_margin_b.setValue(20)
            self.spn_margin_l.setValue(20)
            self.spn_margin_r.setValue(0)
        elif index == 3: # TR
            self.spn_margin_t.setValue(20)
            self.spn_margin_b.setValue(0)
            self.spn_margin_l.setValue(0)
            self.spn_margin_r.setValue(20)
        elif index == 4: # TL
            self.spn_margin_t.setValue(20)
            self.spn_margin_b.setValue(0)
            self.spn_margin_l.setValue(20)
            self.spn_margin_r.setValue(0)

        self.spn_margin_t.blockSignals(False)
        self.spn_margin_b.blockSignals(False)
        self.spn_margin_l.blockSignals(False)
        self.spn_margin_r.blockSignals(False)
        
        self._on_changed()
