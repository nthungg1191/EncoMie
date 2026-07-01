import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow
import subprocess


if sys.platform.startswith("win"):
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
    app = QApplication(sys.argv)
    app.setApplicationName("EncoMie")
    app.setOrganizationName("EncoMie")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
