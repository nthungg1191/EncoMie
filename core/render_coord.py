"""
Cross-instance render coordination.

Running several EncoMie instances at once to render in parallel is a supported
workflow. The goal here is a machine-wide ceiling: however many instances are
rendering (1 or 4), all the ffmpeg processes together should use only about
half of the CPU and leave the rest for the OS and other apps.

Each ffmpeg process used to size its CPU-filter thread pool as if it were the
only renderer on the machine, so 2-3 instances oversubscribed threads and the
box got pegged at 100%.

Every active render now advertises itself with a small file in a shared
directory (one per running ffmpeg, mtime = heartbeat). Any renderer reads the
true machine-wide count and takes an equal slice of a fixed ~50% CPU budget:
one render gets the whole slice, four renders get a quarter each. ffmpeg also
stays at BELOW_NORMAL priority so the reserved half really is available to the
system.

Same spirit as the shared-file license heartbeat: no lock, no daemon; a stale
slot (crashed process) just ages out.
"""

import os
import time
import uuid
from pathlib import Path

from core.app_paths import app_data_dir

# Fraction of logical CPUs the render pipeline as a whole is allowed to use.
# The other half is deliberately left for the OS / foreground apps.
CPU_BUDGET_FRACTION = 0.5

_STALE_SEC = 45          # a slot older than this is treated as dead and swept
_TOUCH_MIN_INTERVAL = 5  # don't rewrite our own slot more often than this


def _slot_dir() -> Path:
    d = app_data_dir() / "render_slots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _live_slots() -> list[Path]:
    now = time.time()
    live: list[Path] = []
    for f in _slot_dir().glob("*.slot"):
        try:
            if now - f.stat().st_mtime < _STALE_SEC:
                live.append(f)
            else:
                f.unlink()  # opportunistic sweep of a dead render's slot
        except OSError:
            pass
    return live


def active_render_count() -> int:
    """Number of ffmpeg renders running right now across every EncoMie instance."""
    return len(_live_slots())


class RenderSlot:
    """Context manager: registers this render in the shared directory for its
    lifetime. Call ``touch()`` periodically from the ffmpeg read loop so the
    slot stays fresh on long renders."""

    def __init__(self):
        self._path = _slot_dir() / f"{os.getpid()}-{uuid.uuid4().hex[:8]}.slot"
        self._last = 0.0

    def __enter__(self) -> "RenderSlot":
        self.touch(force=True)
        return self

    def touch(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last < _TOUCH_MIN_INTERVAL:
            return
        try:
            self._path.write_text(str(now))
            self._last = now
        except OSError:
            pass

    def __exit__(self, *_exc) -> None:
        try:
            self._path.unlink()
        except OSError:
            pass


def cpu_plan(max_concurrent_this_instance: int) -> dict:
    """
    Per-render thread budget so that ALL renders on the machine together stay
    near CPU_BUDGET_FRACTION of the logical CPUs. Call this AFTER entering a
    RenderSlot so the count includes this render.
    """
    logical = os.cpu_count() or 4
    # Floor by this instance's own concurrency: sibling jobs that haven't
    # reached render_pair yet aren't in the slot count yet, so don't hand the
    # first one the whole budget.
    renders = max(active_render_count(), 1, int(max_concurrent_this_instance or 1))

    budget = max(1, int(logical * CPU_BUDGET_FRACTION))
    per = max(1, min(16, budget // renders))

    return {
        "filter_threads": per,
        "encoder_threads": per,  # capped, not 0/auto: N encoders must not each grab every core
    }
