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
