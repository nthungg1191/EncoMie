import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow
import subprocess


if sys.platform.startswith("win"):
    import ctypes
    # Đặt Explicit App User Model ID để Windows Taskbar gắn đúng icon của ứng dụng
    # thay vì icon mặc định của python.exe hoặc icon trong suốt
    try:
        myappid = "encomie.auto_video_editor.app.v1"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    _original_popen = subprocess.Popen

    def _hidden_popen(*args, **kwargs):
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)

        startupinfo = kwargs.get("startupinfo")
        if startupinfo is None:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            kwargs["startupinfo"] = startupinfo

        return _original_popen(*args, **kwargs)

    subprocess.Popen = _hidden_popen

def main():
    # Keep the Qt GUI process unconstrained so UI stays responsive on P-cores
    # while child ffmpeg.exe render processes are isolated to the background
    # CPU set (E-cores / high-index cores) by core.render_coord.apply_cpu_limit.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("EncoMie")
    app.setOrganizationName("EncoMie")

    # Thiết lập Icon cho toàn bộ tiến trình ứng dụng
    from core.app_paths import get_app_icon
    app_icon = get_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    window = MainWindow()
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
