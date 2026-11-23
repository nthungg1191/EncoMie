"""
Widget for configuring a single video layer (1 of 5) in the Edit Video tab.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QFrame, QLineEdit, QScrollArea, QSizePolicy, QLayout
)
from PyQt6.QtCore import pyqtSignal, Qt
from pathlib import Path
import os

from core.video_processor import ImageLayerConfig
from ui.collapsible_section import CollapsibleSection
from ui.flow_layout import FlowWidget, StackedField

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
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        # Inner content widget
        content = QWidget()
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content_lay = QVBoxLayout(content)
        content_lay.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        content_lay.setContentsMargins(2, 8, 2, 24)
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
        source_options = [
            ("Video nền", "Video nền (Background video)"),
            ("Video nguồn", "Theo danh sách chạy (Video nguồn)"),
            ("File cố định…", "File cố định (Static file...)"),
        ]
        for short_text, full_text in source_options:
            self.cmb_source_type.addItem(short_text)
            self.cmb_source_type.setItemData(
                self.cmb_source_type.count() - 1, full_text, Qt.ItemDataRole.ToolTipRole
            )
        self.cmb_source_type.setStyleSheet("font-size: 11px;")
        self.cmb_source_type.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_source_type.setMinimumContentsLength(8)
        self.cmb_source_type.setMinimumWidth(84)
        self.cmb_source_type.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
        self.lbl_path.setMinimumWidth(80)
        self.lbl_path.setStyleSheet("font-size: 11px;")
        self.lbl_path.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        static_lay.addWidget(self.lbl_path)

        self.edit_path = QLineEdit()
        self.edit_path.setReadOnly(True)
        self.edit_path.setPlaceholderText("Chọn file video/ảnh...")
        self.edit_path.setMinimumWidth(84)
        self.edit_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit_path.setStyleSheet("font-size: 11px;")
        static_lay.addWidget(self.edit_path, 1)

        self.btn_browse = QPushButton("Chọn…")
        self.btn_browse.setMinimumWidth(60)
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
        pos_lbl.setMinimumWidth(80)
        pos_lbl.setStyleSheet("font-size: 11px;")
        pos_lbl.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
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
        self.cmb_pos.setMinimumWidth(84)
        self.cmb_pos.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cmb_pos.currentIndexChanged.connect(self._on_pos_changed)
        row2.addWidget(self.cmb_pos, 1)
        t_lay.addLayout(row2)

        self.spn_size = QSpinBox()
        self.spn_size.setRange(10, 150)
        self.spn_size.setValue(30 if self.index == 1 else 15)
        self.spn_size.setSuffix(" %")
        self.spn_size.valueChanged.connect(self._on_changed)
        self.spn_opacity = QSpinBox()
        self.spn_opacity.setRange(10, 100)
        self.spn_opacity.setValue(100)
        self.spn_opacity.setSingleStep(5)
        self.spn_opacity.setSuffix(" %")
        self.spn_opacity.valueChanged.connect(self._on_changed)
        self.spn_speed = QSpinBox()
        self.spn_speed.setRange(10, 300)
        self.spn_speed.setValue(100)
        self.spn_speed.setSuffix(" %")
        self.spn_speed.valueChanged.connect(self._on_changed)
        self.spn_blur = QDoubleSpinBox()
        self.spn_blur.setRange(0.0, 20.0)
        self.spn_blur.setDecimals(1)
        self.spn_blur.setSingleStep(0.5)
        self.spn_blur.setValue(0.0)
        self.spn_blur.setSuffix(" px")
        self.spn_blur.valueChanged.connect(self._on_changed)
        transform_flow = FlowWidget(max_columns=2)
        transform_flow.add_field("Size:", self.spn_size)
        transform_flow.add_field("Độ mờ:", self.spn_opacity)
        self.row_speed_widget = transform_flow.add_field("Tốc độ:", self.spn_speed)
        transform_flow.add_field("Nhòe:", self.spn_blur)
        t_lay.addWidget(transform_flow)
        content_lay.addWidget(self.sec_transform)

        # Section 2: Khoảng lề (Margin) - open by default, baseline positioning.
        self.sec_margin = CollapsibleSection("Khoảng lề (Margin - px)", open_=True)
        margin_flow = FlowWidget(max_columns=2)
        self.spn_margin_t = QSpinBox()
        self.spn_margin_t.setRange(0, 1000)
        self.spn_margin_t.setValue(60 if self.index == 1 else 145)
        self.spn_margin_t.setSuffix(" px")
        self.spn_margin_t.valueChanged.connect(self._on_changed)
        self.spn_margin_b = QSpinBox()
        self.spn_margin_b.setRange(0, 1000)
        self.spn_margin_b.setValue(60 if self.index == 1 else 20)
        self.spn_margin_b.setSuffix(" px")
        self.spn_margin_b.valueChanged.connect(self._on_changed)
        self.spn_margin_l = QSpinBox()
        self.spn_margin_l.setRange(0, 1000)
        self.spn_margin_l.setValue(140 if self.index == 1 else 320)
        self.spn_margin_l.setSuffix(" px")
        self.spn_margin_l.valueChanged.connect(self._on_changed)
        self.spn_margin_r = QSpinBox()
        self.spn_margin_r.setRange(0, 1000)
        self.spn_margin_r.setValue(140 if self.index == 1 else 20)
        self.spn_margin_r.setSuffix(" px")
        self.spn_margin_r.valueChanged.connect(self._on_changed)
        margin_flow.add_field("Trên:", self.spn_margin_t)
        margin_flow.add_field("Dưới:", self.spn_margin_b)
        margin_flow.add_field("Trái:", self.spn_margin_l)
        margin_flow.add_field("Phải:", self.spn_margin_r)
        self.sec_margin.body_layout.addWidget(margin_flow)
        content_lay.addWidget(self.sec_margin)

        # Section 3: Cắt cúp (Crop) - collapsed by default.
        self.sec_crop = CollapsibleSection("Cắt cúp (Crop)")
        crop_flow = FlowWidget(max_columns=2)

        self.btn_crop_mode = QPushButton("✂  Bật Crop Mode")
        self.btn_crop_mode.setCheckable(True)
        self.btn_crop_mode.setStyleSheet(
            "QPushButton { background: #fef3c7; color: #d97706; border: 1px solid #f59e0b; "
            "padding: 4px; border-radius: 4px; font-size: 11px; font-weight: bold; }"
            "QPushButton:checked { background: #f59e0b; color: #ffffff; }"
        )
        self.btn_crop_mode.toggled.connect(self._on_crop_mode_toggled)
        self.sec_crop.body_layout.addWidget(self.btn_crop_mode)
        self.spn_crop_t = QSpinBox()
        self.spn_crop_t.setRange(0, 500)
        self.spn_crop_t.setValue(0)
        self.spn_crop_t.setSuffix(" px")
        self.spn_crop_t.valueChanged.connect(self._on_changed)
        self.spn_crop_b = QSpinBox()
        self.spn_crop_b.setRange(0, 500)
        self.spn_crop_b.setValue(0)
        self.spn_crop_b.setSuffix(" px")
        self.spn_crop_b.valueChanged.connect(self._on_changed)
        self.spn_crop_l = QSpinBox()
        self.spn_crop_l.setRange(0, 500)
        self.spn_crop_l.setValue(0)
        self.spn_crop_l.setSuffix(" px")
        self.spn_crop_l.valueChanged.connect(self._on_changed)
        self.spn_crop_r = QSpinBox()
        self.spn_crop_r.setRange(0, 500)
        self.spn_crop_r.setValue(0)
        self.spn_crop_r.setSuffix(" px")
        self.spn_crop_r.valueChanged.connect(self._on_changed)
        crop_flow.add_field("Trên:", self.spn_crop_t)
        crop_flow.add_field("Dưới:", self.spn_crop_b)
        crop_flow.add_field("Trái:", self.spn_crop_l)
        crop_flow.add_field("Phải:", self.spn_crop_r)
        self.sec_crop.body_layout.addWidget(crop_flow)
        content_lay.addWidget(self.sec_crop)

        # Section 4: Chroma Key - collapsed by default.
        self.sec_chroma = CollapsibleSection("Chroma Key")

        self.chk_chroma_enabled = QCheckBox("Kích hoạt khử nền xanh")
        self.chk_chroma_enabled.setStyleSheet("font-size: 11px;")
        self.chk_chroma_enabled.stateChanged.connect(self._on_chroma_enabled_changed)
        self.sec_chroma.body_layout.addWidget(self.chk_chroma_enabled)

        self.chroma_params_frame = FlowWidget(max_columns=2)
        self.spn_chroma_sim = QDoubleSpinBox()
        self.spn_chroma_sim.setRange(0.01, 1.00)
        self.spn_chroma_sim.setSingleStep(0.01)
        self.spn_chroma_sim.setValue(0.38)
        self.spn_chroma_sim.valueChanged.connect(self._on_changed)
        self.spn_chroma_blend = QDoubleSpinBox()
        self.spn_chroma_blend.setRange(0.00, 1.00)
        self.spn_chroma_blend.setSingleStep(0.01)
        self.spn_chroma_blend.setValue(0.08)
        self.spn_chroma_blend.valueChanged.connect(self._on_changed)
        self.btn_chroma_color = QPushButton()
        self.btn_chroma_color.setStyleSheet(f"background-color: {self.chroma_key_color}; border: 1px solid #cccccc; border-radius: 4px;")
        self.btn_chroma_color.clicked.connect(self._on_color_picker_clicked)

        self.btn_eyedropper = QPushButton("Hút màu từ ảnh")
        self.btn_eyedropper.setToolTip("Hút màu từ ảnh (Eyedropper)")
        self.btn_eyedropper.setStyleSheet("font-size: 11px;")
        self.btn_eyedropper.clicked.connect(self._on_eyedropper_clicked)
        self.spn_chroma_spill = QDoubleSpinBox()
        self.spn_chroma_spill.setRange(0.00, 1.00)
        self.spn_chroma_spill.setSingleStep(0.05)
        self.spn_chroma_spill.setValue(0.00)
        self.spn_chroma_spill.valueChanged.connect(self._on_changed)
        self.chroma_params_frame.add_field("Độ nhạy:", self.spn_chroma_sim)
        self.chroma_params_frame.add_field("Độ mềm:", self.spn_chroma_blend)
        self.chroma_params_frame.add_field("Màu khử:", self.btn_chroma_color)
        self.chroma_params_frame.add_field("Tràn màu:", self.spn_chroma_spill)
        self.sec_chroma.body_layout.addWidget(self.btn_eyedropper)

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

        self.luma_params_frame = FlowWidget()

        # Threshold: where on the black<->white range keying happens. Low =
        # remove dark/black backgrounds (most common), high = remove white.
        # Tolerance: width of the band around threshold that's keyed out.
        # Softness: width of the soft alpha ramp beyond that band's edge.
        self.spn_luma_threshold = QDoubleSpinBox()
        self.spn_luma_threshold.setRange(0.00, 1.00)
        self.spn_luma_threshold.setSingleStep(0.01)
        self.spn_luma_threshold.setValue(0.10)
        self.spn_luma_threshold.setToolTip("0 = xóa nền tối/đen  ·  1 = xóa nền sáng/trắng")
        self.spn_luma_threshold.valueChanged.connect(self._on_changed)
        self.spn_luma_tolerance = QDoubleSpinBox()
        self.spn_luma_tolerance.setRange(0.00, 1.00)
        self.spn_luma_tolerance.setSingleStep(0.01)
        self.spn_luma_tolerance.setValue(0.05)
        self.spn_luma_tolerance.setToolTip("Vùng độ sáng quanh Ngưỡng cũng bị xóa")
        self.spn_luma_tolerance.valueChanged.connect(self._on_changed)
        self.spn_luma_softness = QDoubleSpinBox()
        self.spn_luma_softness.setRange(0.00, 1.00)
        self.spn_luma_softness.setSingleStep(0.01)
        self.spn_luma_softness.setValue(0.05)
        self.spn_luma_softness.valueChanged.connect(self._on_changed)
        self.luma_params_frame.add_field("Ngưỡng:", self.spn_luma_threshold)
        self.luma_params_frame.add_field("Dung sai:", self.spn_luma_tolerance)
        self.luma_params_frame.add_field("Mềm viền:", self.spn_luma_softness)

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

        # Numeric controls must retain enough room for four digits and arrows.
        for _sb in content.findChildren((QSpinBox, QDoubleSpinBox)):
            if isinstance(_sb.parentWidget(), StackedField):
                continue
            _sb.setMinimumWidth(84)
            _sb.setMaximumWidth(110)
            _sb.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            _sb.setAlignment(Qt.AlignmentFlag.AlignRight)

        form_labels = {
            "Đường dẫn:", "Vị trí đè:", "Size:", "Opacity:", "Speed:",
            "Blur:", "Trên:", "Dưới:", "Trái:", "Phải:",
            "Cắt Trên:", "Cắt Dưới:", "Cắt Trái:", "Cắt Phải:",
            "Độ nhạy:", "Độ mềm:", "Màu khử:", "Khử tràn màu:",
            "Ngưỡng:", "Dung sai:", "Độ mềm viền:",
        }
        for _label in content.findChildren(QLabel):
            if _label.text() in form_labels and not isinstance(_label.parentWidget(), StackedField):
                _label.setMinimumWidth(max(56, _label.sizeHint().width() + 4))
                _label.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                _label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
                _label.setStyleSheet("font-size: 11px; color: #636366; border: none;")

        # Set scroll area widget
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Default state: Only Layer 1 is active by default
        self.chk_enabled.setChecked(self.index == 1)

        # Clean initial path
        self.edit_path.setText("")

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
