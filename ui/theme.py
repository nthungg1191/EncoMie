"""Centralized UI theme palette, spinbox icon lookup, and QSS builders."""

from core.app_paths import get_resource_path

# Shared UI colour tokens
C_BG             = "#f4f4f7"
C_SECTION_BG     = "#ffffff"
C_ELEVATED_BG    = "#f2f2f7"
C_ACCENT         = "#007aff"
C_ACCENT_DIM     = "#e5e5ea"
C_SUCCESS        = "#34c759"
C_TEXT           = "#1c1c1e"
C_TEXT_MUTED     = "#636366"
C_BORDER         = "#e5e5ea"
C_HOVER          = "#f2f2f7"
C_SECTION_BORDER = "#e5e5ea"
C_PREVIEW_BG     = "#ffffff"
C_PREVIEW_BORDER = "#d1d1d6"


def get_spinbox_icons() -> dict[str, str]:
    """Resolve spinbox up/down arrow icon paths (PNG preferred over SVG)."""
    up_path = get_resource_path("Asset/Img/spin_up.png")
    if not up_path.exists():
        up_path = get_resource_path("Asset/Img/spin_up.svg")

    down_path = get_resource_path("Asset/Img/spin_down.png")
    if not down_path.exists():
        down_path = get_resource_path("Asset/Img/spin_down.svg")

    up_hover_path = get_resource_path("Asset/Img/spin_up_hover.png")
    down_hover_path = get_resource_path("Asset/Img/spin_down_hover.png")

    up_icon = str(up_path).replace("\\", "/")
    down_icon = str(down_path).replace("\\", "/")
    up_hover_icon = str(up_hover_path).replace("\\", "/") if up_hover_path.exists() else up_icon
    down_hover_icon = str(down_hover_path).replace("\\", "/") if down_hover_path.exists() else down_icon

    return {
        "up": up_icon,
        "down": down_icon,
        "up_hover": up_hover_icon,
        "down_hover": down_hover_icon,
    }


def spinbox_arrows_qss(
    *,
    button_width: int = 18,
    button_height: int = 13,
    button_bg: str = "#f8fafc",
    border_color: str = "#cbd5e1",
    divider_color: str = "#e2e8f0",
    hover_bg: str | None = "#e2e8f0",
    radius: int = 5,
    include_double: bool = True,
) -> str:
    """Build reusable QSS rules for QSpinBox (and optionally QDoubleSpinBox) up/down buttons & arrows."""
    icons = get_spinbox_icons()
    targets = ("QSpinBox", "QDoubleSpinBox") if include_double else ("QSpinBox",)
    up_btn = ", ".join(f"{t}::up-button" for t in targets)
    down_btn = ", ".join(f"{t}::down-button" for t in targets)
    up_btn_hover = ", ".join(f"{t}::up-button:hover" for t in targets)
    down_btn_hover = ", ".join(f"{t}::down-button:hover" for t in targets)
    up_arr = ", ".join(f"{t}::up-arrow" for t in targets)
    up_arr_hover = ", ".join(f"{t}::up-arrow:hover" for t in targets)
    down_arr = ", ".join(f"{t}::down-arrow" for t in targets)
    down_arr_hover = ", ".join(f"{t}::down-arrow:hover" for t in targets)

    hover_block = (
        f"""
        {up_btn_hover},
        {down_btn_hover} {{
            background-color: {hover_bg};
        }}
        """
        if hover_bg
        else ""
    )

    return f"""
        {up_btn} {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: {button_width}px;
            height: {button_height}px;
            border-left: 1px solid {border_color};
            border-bottom: 0.5px solid {divider_color};
            border-top-right-radius: {radius}px;
            background-color: {button_bg};
            margin-top: 1px;
            margin-right: 1px;
        }}

        {down_btn} {{
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: {button_width}px;
            height: {button_height}px;
            border-left: 1px solid {border_color};
            border-bottom-right-radius: {radius}px;
            background-color: {button_bg};
            margin-bottom: 1px;
            margin-right: 1px;
        }}
        {hover_block}
        {up_arr} {{
            image: url("{icons['up']}");
            width: 9px;
            height: 9px;
        }}

        {up_arr_hover} {{
            image: url("{icons['up_hover']}");
        }}

        {down_arr} {{
            image: url("{icons['down']}");
            width: 9px;
            height: 9px;
        }}

        {down_arr_hover} {{
            image: url("{icons['down_hover']}");
        }}
    """


def build_main_window_qss() -> str:
    """Return the global application stylesheet for MainWindow."""
    spinbox_rules = spinbox_arrows_qss(
        button_width=18,
        button_height=13,
        button_bg="#f8fafc",
        border_color="#cbd5e1",
        divider_color="#e2e8f0",
        hover_bg="#e2e8f0",
        radius=5,
        include_double=True,
    )

    return (
        """
        /* Global Reset & Typography */
        QWidget {
            font-family: "Be Vietnam Pro", "Inter", "Segoe UI", sans-serif;
            font-size: 12px;
            color: #0f172a;
            outline: none;
        }

        QMainWindow, QDialog {
            background-color: #f8fafc;
        }

        /* Section Cards & GroupBoxes */
        QGroupBox, .section-card {
            background-color: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            margin-top: 8px;
            padding: 8px 8px 6px 8px;
            font-weight: 700;
            font-size: 11px;
            color: #475569;
        }

        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 10px;
            padding: 0 4px;
            background-color: #f8fafc;
            color: #475569;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        /* Form Controls */
        QLineEdit, QComboBox {
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 2px 6px;
            color: #0f172a;
            font-size: 11px;
            min-height: 22px;
        }

        QSpinBox, QDoubleSpinBox {
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 1px 4px 1px 6px;
            color: #0f172a;
            font-size: 11px;
            min-height: 22px;
        }

        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
            border: 1.5px solid #007aff;
            background-color: #ffffff;
        }
        """
        + spinbox_rules
        + """
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 20px;
            border-left-width: 0px;
        }

        QComboBox QAbstractItemView {
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            selection-background-color: #eff6ff;
            selection-color: #007aff;
            padding: 4px;
        }

        /* PushButtons */
        QPushButton {
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 5px 12px;
            color: #0f172a;
            font-weight: 500;
            font-size: 11px;
        }

        QPushButton:hover {
            background-color: #f1f5f9;
            border-color: #007aff;
            color: #007aff;
        }

        QPushButton:pressed {
            background-color: #e2e8f0;
        }

        /* Tables & Lists */
        QTableWidget, QTableView {
            background-color: #ffffff;
            alternate-background-color: #f8fafc;
            border: 1px solid #e2e8f0;
            gridline-color: #f1f5f9;
            color: #0f172a;
            selection-background-color: #eff6ff;
            selection-color: #007aff;
            border-radius: 8px;
            font-size: 11px;
        }

        QHeaderView::section {
            background-color: #f8fafc;
            color: #64748b;
            padding: 6px 8px;
            font-weight: 700;
            font-size: 10px;
            border: none;
            border-bottom: 1px solid #e2e8f0;
            text-transform: uppercase;
        }

        /* Progress Bar */
        QProgressBar {
            background-color: #e2e8f0;
            border: none;
            border-radius: 4px;
            text-align: center;
            color: #0f172a;
            font-size: 10px;
            font-weight: 600;
            height: 16px;
        }

        QProgressBar::chunk {
            background-color: #10b981;
            border-radius: 4px;
        }

        /* ScrollBar */
        QScrollBar:vertical {
            border: none;
            background: #f8fafc;
            width: 6px;
            border-radius: 3px;
        }

        QScrollBar::handle:vertical {
            background: #cbd5e1;
            border-radius: 3px;
            min-height: 20px;
        }

        QScrollBar::handle:vertical:hover {
            background: #94a3b8;
        }

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }

        /* Tab Widget */
        QTabWidget::pane {
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            background-color: #ffffff;
        }

        QTabBar::tab {
            background: #f8fafc;
            color: #64748b;
            border: 1px solid #e2e8f0;
            padding: 5px 12px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            margin-right: 2px;
            font-size: 11px;
            font-weight: 600;
        }

        QTabBar::tab:selected {
            background: #ffffff;
            color: #007aff;
            border-bottom: 2px solid #007aff;
            font-weight: 700;
        }
        """
    )
