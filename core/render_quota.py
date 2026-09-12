"""
Per-day render quota for the Free plan (`Entitlements.max_videos`).

Enforced client-side, in the same spirit and with the same residual risk as
the other entitlement clamps in core/entitlements.py: it stops a casual free
user from exceeding the daily cap, not a determined one who edits/deletes the
local counter file.

The count is scoped to BOTH the calendar date and the active licence key: it
resets at midnight, and each key has its own tally for the day. Rendering on a
Pro key then activating a Free key to test starts the Free key from zero
instead of inheriting the Pro key's renders (and switching back keeps each
key's own count).

File shape: ``{"date": "YYYY-MM-DD", "keys": {"<tag>": <count>}}``.
"""

import json
import hashlib
from pathlib import Path
from datetime import date

from core.app_paths import app_data_dir


def _quota_path() -> Path:
    return app_data_dir() / "render_quota.json"


def _key_tag(key: str) -> str:
    key = (key or "").strip()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] if key else "_"


def _load_today() -> dict:
    """`{tag: count}` for today (empty if the file is missing / from another day)."""
    p = _quota_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if str(data.get("date", "")) != date.today().isoformat():
            return {}
        keys = data.get("keys")
        if isinstance(keys, dict):
            return {str(k): int(v) for k, v in keys.items()}
        # Old single-count shape (no per-key breakdown): attribute it to the
        # unknown-key bucket so it doesn't count against any real key.
        if "count" in data:
            return {"_": int(data.get("count", 0))}
        return {}
    except Exception:
        return {}


def _save_today(keys: dict) -> None:
    try:
        _quota_path().write_text(
            json.dumps({"date": date.today().isoformat(), "keys": keys}),
            encoding="utf-8",
        )
    except Exception:
        pass


def today_count(key: str = "") -> int:
    """Videos rendered today under `key`."""
    return _load_today().get(_key_tag(key), 0)


def remaining_today(max_videos: int, key: str = "") -> int:
    """Videos still allowed today. `max_videos < 0` means unlimited (returns -1)."""
    if max_videos is None or max_videos < 0:
        return -1
    return max(0, max_videos - today_count(key))


def record_render(key: str = "") -> int:
    """Call once per successfully completed render. Returns the new count for `key`."""
    keys = _load_today()
    tag = _key_tag(key)
    keys[tag] = keys.get(tag, 0) + 1
    _save_today(keys)
    return keys[tag]
