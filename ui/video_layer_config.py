"""
Widget for configuring a single video layer (1 of 5) in the Edit Video tab.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QSpinBox, QCheckBox, QPushButton,
    QGroupBox, QFrame, QLineEdit, QToolButton
)
from PyQt6.QtCore import pyqtSignal, Qt
from pathlib import Path
import os

from core.video_processor import ImageLayerConfig

class CollapsibleSection(QWidget):
    toggled = pyqtSignal(bool) # Emitted when expanded/collapsed

    def __init__(self, title: str, checkable: bool = False, checked: bool = False, parent=None):
        super().__init__(parent)
        self.is_expanded = False
        self.checkable = checkable

        # Main layout
        self.main_lay = QVBoxLayout(self)
        self.main_lay.setContentsMargins(0, 0, 0, 1) # 1px gap below section
        self.main_lay.setSpacing(0)

        # Header bar (clickable horizontal widget)
        self.header = QFrame()
        self.header.setObjectName("HeaderFrame")
        self.header.setFixedHeight(30)
        self.header.setStyleSheet("""
            QFrame#HeaderFrame {
                background-color: #f1f5f9;
                border-bottom: 1px solid #cbd5e1;
                border-radius: 2px;
            }
            QFrame#HeaderFrame:hover {
                background-color: #e2e8f0;
            }
            QFrame#HeaderFrame QLabel {
                background-color: transparent;
                border: none;
                color: #334155;
            }
            QFrame#HeaderFrame QToolButton {
                background-color: transparent;
                border: none;
            }
        """)
        header_lay = QHBoxLayout(self.header)
        header_lay.setContentsMargins(8, 4, 8, 4)
        header_lay.setSpacing(6)

        # Arrow indicator button (non-focusable, flat)
        self.btn_arrow = QToolButton()
        self.btn_arrow.setArrowType(Qt.ArrowType.RightArrow)
        self.btn_arrow.setStyleSheet("border: none; background: transparent; color: #64748b; padding: 0;")
        self.btn_arrow.setFixedSize(12, 12)
        self.btn_arrow.clicked.connect(self.toggle)
        header_lay.addWidget(self.btn_arrow)

        # Title Label
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("font-size: 12px; font-weight: normal; color: #334155; background-color: transparent;")
        header_lay.addWidget(self.lbl_title, 1)

        # Optional Checkbox on the right
        self.chk_enable = None
        if self.checkable:
            self.chk_enable = QCheckBox()
            self.chk_enable.setChecked(checked)
            self.chk_enable.setToolTip("Kích hoạt tính năng này")
            self.chk_enable.setStyleSheet("QCheckBox { background: transparent; } QCheckBox::indicator { width: 12px; height: 12px; }")
            header_lay.addWidget(self.chk_enable)

        self.main_lay.addWidget(self.header)

        # Content area (container widget)
        self.content_container = QWidget()
        self.content_lay = QVBoxLayout(self.content_container)
        self.content_lay.setContentsMargins(4, 4, 4, 4)
        self.content_container.setVisible(False)
        self.main_lay.addWidget(self.content_container)

        # Make header clickable (filter mouse clicks)
        self.header.mousePressEvent = self._on_header_clicked

    def _on_header_clicked(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # If clicked on the checkbox area, don't toggle collapse
            if self.chk_enable:
                # Map click position to header coordinates
                if self.chk_enable.geometry().contains(event.position().toPoint()):
                    return # Let the checkbox handle it
            self.toggle()

    def toggle(self):
        self.is_expanded = not self.is_expanded
        self.btn_arrow.setArrowType(
            Qt.ArrowType.DownArrow if self.is_expanded else Qt.ArrowType.RightArrow
        )
        self.content_container.setVisible(self.is_expanded)
        self.toggled.emit(self.is_expanded)

    def isChecked(self) -> bool:
        if self.chk_enable:
            return self.chk_enable.isChecked()
        return True

    def setChecked(self, checked: bool):
        if self.chk_enable:
            self.chk_enable.blockSignals(True)
            self.chk_enable.setChecked(checked)
            self.chk_enable.blockSignals(False)

    def setExpanded(self, expanded: bool):
        if self.is_expanded != expanded:
            self.toggle()

class VideoLayerConfigWidget(QWidget):
    changed = pyqtSignal()

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self._init_ui()

    def _init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

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
        self.cmb_source_type.currentIndexChanged.connect(self._on_source_type_changed)
        row1.addWidget(self.cmb_source_type)
        lay.addLayout(row1)

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

        lay.addWidget(self.static_file_frame)
        self.static_file_frame.setVisible(False) # Default is Batch file

        # Row 2: Vị trí neo (Alignment)
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
        self.cmb_pos.currentIndexChanged.connect(self._on_pos_changed)
        row2.addWidget(self.cmb_pos, 1)
        lay.addLayout(row2)

        # Row 3: Cỡ (Scale %) & Bo góc (Radius px)
        row3 = QHBoxLayout()
        row3.setSpacing(10)

        sz_lbl = QLabel("Cỡ (%):")
        sz_lbl.setStyleSheet("font-size: 11px;")
        row3.addWidget(sz_lbl)

        self.spn_size = QSpinBox()
        self.spn_size.setRange(10, 100)
        self.spn_size.setValue(30 if self.index == 1 else 15)
        self.spn_size.setStyleSheet("font-size: 11px;")
        self.spn_size.valueChanged.connect(self._on_changed)
        row3.addWidget(self.spn_size, 1)

        op_lbl = QLabel("Độ mờ (%):")
        op_lbl.setStyleSheet("font-size: 11px;")
        row3.addWidget(op_lbl)

        self.spn_opacity = QSpinBox()
        self.spn_opacity.setRange(10, 100)
        self.spn_opacity.setValue(100)
        self.spn_opacity.setSingleStep(5)
        self.spn_opacity.setStyleSheet("font-size: 11px;")
        self.spn_opacity.valueChanged.connect(self._on_changed)
        row3.addWidget(self.spn_opacity, 1)
        lay.addLayout(row3)

        # Row 4: Margins Group
        self.margin_sec = CollapsibleSection("Căn chỉnh khoảng lề (Margin - px)", checkable=False)
        margin_lay = QGridLayout()
        margin_lay.setContentsMargins(4, 4, 4, 4)
        margin_lay.setSpacing(6)

        # Top
        margin_lay.addWidget(QLabel("Trên:"), 0, 0)
        self.spn_margin_t = QSpinBox()
        self.spn_margin_t.setRange(0, 1000)
        self.spn_margin_t.setValue(60 if self.index == 1 else 145)
        self.spn_margin_t.valueChanged.connect(self._on_changed)
        margin_lay.addWidget(self.spn_margin_t, 0, 1)

        # Bottom
        margin_lay.addWidget(QLabel("Dưới:"), 0, 2)
        self.spn_margin_b = QSpinBox()
        self.spn_margin_b.setRange(0, 1000)
        self.spn_margin_b.setValue(60 if self.index == 1 else 20)
        self.spn_margin_b.valueChanged.connect(self._on_changed)
        margin_lay.addWidget(self.spn_margin_b, 0, 3)

        # Left
        margin_lay.addWidget(QLabel("Trái:"), 1, 0)
        self.spn_margin_l = QSpinBox()
        self.spn_margin_l.setRange(0, 1000)
        self.spn_margin_l.setValue(140 if self.index == 1 else 320)
        self.spn_margin_l.valueChanged.connect(self._on_changed)
        margin_lay.addWidget(self.spn_margin_l, 1, 1)

        # Right
        margin_lay.addWidget(QLabel("Phải:"), 1, 2)
        self.spn_margin_r = QSpinBox()
        self.spn_margin_r.setRange(0, 1000)
        self.spn_margin_r.setValue(140 if self.index == 1 else 20)
        self.spn_margin_r.valueChanged.connect(self._on_changed)
        margin_lay.addWidget(self.spn_margin_r, 1, 3)

        self.margin_sec.content_lay.addLayout(margin_lay)
        self.margin_sec.toggled.connect(self._on_changed)
        lay.addWidget(self.margin_sec)

        # Row 5: Crop Group
        self.crop_sec = CollapsibleSection("Cắt cúp khung hình (Crop - px)", checkable=True, checked=False)
        crop_lay = QGridLayout()
        crop_lay.setContentsMargins(4, 4, 4, 4)
        crop_lay.setSpacing(6)

        # Crop Top
        crop_lay.addWidget(QLabel("Cắt Trên:"), 0, 0)
        self.spn_crop_t = QSpinBox()
        self.spn_crop_t.setRange(0, 500)
        self.spn_crop_t.setValue(0)
        self.spn_crop_t.valueChanged.connect(self._on_changed)
        crop_lay.addWidget(self.spn_crop_t, 0, 1)

        # Crop Bottom
        crop_lay.addWidget(QLabel("Cắt Dưới:"), 0, 2)
        self.spn_crop_b = QSpinBox()
        self.spn_crop_b.setRange(0, 500)
        self.spn_crop_b.setValue(0)
        self.spn_crop_b.valueChanged.connect(self._on_changed)
        crop_lay.addWidget(self.spn_crop_b, 0, 3)

        # Crop Left
        crop_lay.addWidget(QLabel("Cắt Trái:"), 1, 0)
        self.spn_crop_l = QSpinBox()
        self.spn_crop_l.setRange(0, 500)
        self.spn_crop_l.setValue(0)
        self.spn_crop_l.valueChanged.connect(self._on_changed)
        crop_lay.addWidget(self.spn_crop_l, 1, 1)

        # Crop Right
        crop_lay.addWidget(QLabel("Cắt Phải:"), 1, 2)
        self.spn_crop_r = QSpinBox()
        self.spn_crop_r.setRange(0, 500)
        self.spn_crop_r.setValue(0)
        self.spn_crop_r.valueChanged.connect(self._on_changed)
        crop_lay.addWidget(self.spn_crop_r, 1, 3)

        self.crop_sec.content_lay.addLayout(crop_lay)
        self.crop_sec.chk_enable.stateChanged.connect(self._on_changed)
        self.crop_sec.toggled.connect(self._on_changed)
        lay.addWidget(self.crop_sec)

        # Row 6: Chroma Key Group
        self.chroma_sec = CollapsibleSection("Xóa phông nền (Chroma Key)", checkable=True, checked=False)
        chroma_lay = QGridLayout()
        chroma_lay.setContentsMargins(4, 4, 4, 4)
        chroma_lay.setSpacing(6)

        # Color picker
        chroma_lay.addWidget(QLabel("Màu phông:"), 0, 0)
        
        color_row = QHBoxLayout()
        color_row.setSpacing(4)
        self.btn_key_color = QPushButton("Chọn màu")
        self.btn_key_color.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.btn_key_color.clicked.connect(self._choose_key_color)
        color_row.addWidget(self.btn_key_color)
        
        self.lbl_color_preview = QLabel()
        self.lbl_color_preview.setFixedSize(16, 16)
        self.lbl_color_preview.setStyleSheet("background-color: #00FF00; border: 1px solid #555;")
        color_row.addWidget(self.lbl_color_preview)
        
        # Color value holder
        self.chromakey_color_hex = "0x00FF00"
        chroma_lay.addLayout(color_row, 0, 1)

        # Similarity Spinbox
        chroma_lay.addWidget(QLabel("Độ nhạy (Sim %):"), 1, 0)
        self.spn_similarity = QSpinBox()
        self.spn_similarity.setRange(1, 100)
        self.spn_similarity.setValue(15) # Default 15%
        self.spn_similarity.valueChanged.connect(self._on_changed)
        chroma_lay.addWidget(self.spn_similarity, 1, 1)

        # Blend Spinbox
        chroma_lay.addWidget(QLabel("Mịn viền (Blend %):"), 1, 2)
        self.spn_blend = QSpinBox()
        self.spn_blend.setRange(0, 100)
        self.spn_blend.setValue(10) # Default 10%
        self.spn_blend.valueChanged.connect(self._on_changed)
        chroma_lay.addWidget(self.spn_blend, 1, 3)

        self.chroma_sec.content_lay.addLayout(chroma_lay)
        self.chroma_sec.chk_enable.stateChanged.connect(self._on_changed)
        self.chroma_sec.toggled.connect(self._on_changed)
        lay.addWidget(self.chroma_sec)

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

    def _on_source_type_changed(self, idx: int):
        self.static_file_frame.setVisible(idx == 2)
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
            self._on_changed()

    def _choose_key_color(self):
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor
        # Parse current hex color
        color_str = self.chromakey_color_hex.replace("0x", "#")
        initial_color = QColor(color_str)
        color = QColorDialog.getColor(initial_color, self, "Chọn màu phông nền cần xóa")
        if color.isValid():
            hex_name = color.name().upper() # e.g. #00FF00
            self.chromakey_color_hex = hex_name.replace("#", "0x")
            self.lbl_color_preview.setStyleSheet(f"background-color: {hex_name}; border: 1px solid #555;")
            self._on_changed()

    def _on_changed(self):
        self.changed.emit()

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
            margin_t=self.spn_margin_t.value() if self.margin_sec.isChecked() else 0,
            margin_b=self.spn_margin_b.value() if self.margin_sec.isChecked() else 0,
            margin_l=self.spn_margin_l.value() if self.margin_sec.isChecked() else 0,
            margin_r=self.spn_margin_r.value() if self.margin_sec.isChecked() else 0
        )
        # Extend config dynamically with crop/radius
        cfg_obj.crop_t = self.spn_crop_t.value() if self.crop_sec.isChecked() else 0
        cfg_obj.crop_b = self.spn_crop_b.value() if self.crop_sec.isChecked() else 0
        cfg_obj.crop_l = self.spn_crop_l.value() if self.crop_sec.isChecked() else 0
        cfg_obj.crop_r = self.spn_crop_r.value() if self.crop_sec.isChecked() else 0
        cfg_obj.radius = 0
        cfg_obj.source_type = idx # Save index
        cfg_obj.chromakey_enabled = self.chroma_sec.isChecked()
        cfg_obj.chromakey_color = self.chromakey_color_hex
        cfg_obj.chromakey_similarity = self.spn_similarity.value() / 100.0
        cfg_obj.chromakey_blend = self.spn_blend.value() / 100.0
        
        # Save checkable states
        cfg_obj.margin_enabled = self.margin_sec.isChecked()
        cfg_obj.crop_enabled = self.crop_sec.isChecked()
        return cfg_obj

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
        
        # Margins restore
        self.spn_margin_t.setValue(cfg_obj.margin_t)
        self.spn_margin_b.setValue(cfg_obj.margin_b)
        self.spn_margin_l.setValue(cfg_obj.margin_l)
        self.spn_margin_r.setValue(cfg_obj.margin_r)

        margin_enabled = getattr(cfg_obj, "margin_enabled", True)
        self.margin_sec.setChecked(margin_enabled)
        self.margin_sec.setExpanded(True) # Margins always expanded by default

        # Crops restore
        self.spn_crop_t.setValue(getattr(cfg_obj, "crop_t", 0))
        self.spn_crop_b.setValue(getattr(cfg_obj, "crop_b", 0))
        self.spn_crop_l.setValue(getattr(cfg_obj, "crop_l", 0))
        self.spn_crop_r.setValue(getattr(cfg_obj, "crop_r", 0))

        crop_enabled = getattr(cfg_obj, "crop_enabled", False)
        # Fallback: if any crop values are non-zero, force crop_sec to be checked
        if getattr(cfg_obj, "crop_t", 0) > 0 or getattr(cfg_obj, "crop_b", 0) > 0 or getattr(cfg_obj, "crop_l", 0) > 0 or getattr(cfg_obj, "crop_r", 0) > 0:
            crop_enabled = True
        self.crop_sec.setChecked(crop_enabled)
        self.crop_sec.setExpanded(crop_enabled)

        # Chroma key restore
        ch_enabled = getattr(cfg_obj, "chromakey_enabled", False)
        ch_color = getattr(cfg_obj, "chromakey_color", "0x00FF00")
        ch_similarity = int(getattr(cfg_obj, "chromakey_similarity", 0.15) * 100)
        ch_blend = int(getattr(cfg_obj, "chromakey_blend", 0.10) * 100)

        self.chroma_sec.setChecked(ch_enabled)
        self.chroma_sec.setExpanded(ch_enabled)

        self.chromakey_color_hex = ch_color
        hex_color = ch_color.replace("0x", "#")
        self.lbl_color_preview.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #555;")

        self.spn_similarity.blockSignals(True)
        self.spn_similarity.setValue(ch_similarity)
        self.spn_similarity.blockSignals(False)

        self.spn_blend.blockSignals(True)
        self.spn_blend.setValue(ch_blend)
        self.spn_blend.blockSignals(False)

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
