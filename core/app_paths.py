"""
Single source of truth for EncoMie's per-user data directory.

Used by the license cache (license_manager), the Free-plan daily render counter
(render_quota) and the cross-instance render coordination slots (render_coord)
so the three can't drift to different locations.
"""

import os
import sys
from pathlib import Path


def app_data_dir() -> Path:
    """`%APPDATA%\\EncoMie` on Windows, `~/.config/encomie` elsewhere. Created if missing."""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home())) / "EncoMie"
    else:
        base = Path.home() / ".config" / "encomie"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_resource_path(relative_path: str) -> Path:
    """
    Resolve resource paths safely across:
    1. PyInstaller onefile (_MEIPASS)
    2. Frozen executables (Nuitka / PyInstaller onedir)
    3. Development source tree
    """
    # 1. PyInstaller onefile temp folder
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / relative_path
        if p.exists():
            return p

    # 2. Frozen binary folder (sys.executable parent)
    if getattr(sys, "frozen", False):
        p = Path(sys.executable).parent / relative_path
        if p.exists():
            return p

    # 3. Development root (workspace root)
    root = Path(__file__).resolve().parent.parent
    p = root / relative_path
    if p.exists():
        return p

    # Fallback to current working directory
    return (Path.cwd() / relative_path).resolve()


def get_bin_dir() -> Path:
    """Resolve the local `bin/` directory containing bundled FFmpeg/FFprobe binaries."""
    if getattr(sys, "frozen", False):
        exe_bin_dir = Path(sys.executable).parent / "bin"
        if (exe_bin_dir / "ffmpeg.exe").exists():
            return exe_bin_dir
    return Path(__file__).resolve().parent.parent / "bin"


def get_ffmpeg_path() -> str:
    """Return path to bundled `ffmpeg.exe` if present, otherwise `'ffmpeg'` on PATH."""
    candidate = get_bin_dir() / "ffmpeg.exe"
    return str(candidate) if candidate.exists() else "ffmpeg"


def get_ffprobe_path() -> str:
    """Return path to bundled `ffprobe.exe` if present, otherwise `'ffprobe'` on PATH."""
    candidate = get_bin_dir() / "ffprobe.exe"
    return str(candidate) if candidate.exists() else "ffprobe"


def get_app_icon():
    """
    Load the application QIcon with all available multi-resolution frames (16x16 to 256x256).
    """
    from PyQt6.QtGui import QIcon
    icon = QIcon()
    for rel_name in ["Asset/Img/Logo.ico", "Asset/Img/Logo_square.png", "Asset/Img/Logo.png"]:
        p = get_resource_path(rel_name)
        if p.exists():
            icon.addFile(str(p))
    return icon
