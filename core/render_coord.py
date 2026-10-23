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
import struct
import sys
import time
import uuid
from functools import lru_cache
from pathlib import Path

from core.app_paths import app_data_dir

# Fraction of logical CPUs the whole application is allowed to run on. Every
# EncoMie instance uses the same CPU set, so more instances cannot expand it.
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


def allowed_cpu_count(logical: int | None = None) -> int:
    """Maximum logical CPUs shared by all instances (never over 50%)."""
    total = max(1, int(logical if logical is not None else (os.cpu_count() or 1)))
    return max(1, int(total * CPU_BUDGET_FRACTION))


def allowed_cpu_ids(logical: int | None = None) -> tuple[int, ...]:
    """Fallback CPU indices when Windows CPU topology is unavailable."""
    total = max(1, int(logical if logical is not None else (os.cpu_count() or 1)))
    count = allowed_cpu_count(total)
    return tuple(range(total - count, total))


def _select_cpu_sets(records: list[tuple[int, int, int]], count: int) -> tuple[int, ...]:
    """Choose CPU Set IDs by efficiency, spreading work across physical cores.

    Each record is ``(cpu_set_id, core_index, efficiency_class)``. Windows uses
    a larger EfficiencyClass for faster cores, so ascending order selects
    efficient E-cores before P-cores. Within a class, one logical processor per
    physical core is selected before SMT siblings.
    """
    selected: list[int] = []
    for efficiency in sorted({record[2] for record in records}):
        tier = sorted((r for r in records if r[2] == efficiency), key=lambda r: (r[1], r[0]))
        seen_cores: set[int] = set()
        for cpu_set_id, core_index, _ in tier:
            if core_index not in seen_cores:
                selected.append(cpu_set_id)
                seen_cores.add(core_index)
                if len(selected) == count:
                    return tuple(selected)
        for cpu_set_id, core_index, _ in tier:
            if cpu_set_id not in selected:
                selected.append(cpu_set_id)
                if len(selected) == count:
                    return tuple(selected)
    return tuple(selected)


@lru_cache(maxsize=1)
def _windows_cpu_topology() -> tuple[tuple[int, int, int, int, int], ...]:
    """Return (CPU Set ID, group, logical index, core index, efficiency)."""
    if sys.platform != "win32":
        return ()

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    query = getattr(kernel32, "GetSystemCpuSetInformation", None)
    if query is None:
        return ()
    query.argtypes = [ctypes.c_void_p, wintypes.ULONG,
                      ctypes.POINTER(wintypes.ULONG), wintypes.HANDLE, wintypes.ULONG]
    query.restype = wintypes.BOOL

    required = wintypes.ULONG()
    query(None, 0, ctypes.byref(required), None, 0)
    if required.value == 0:
        return ()
    buffer = ctypes.create_string_buffer(required.value)
    if not query(buffer, required.value, ctypes.byref(required), None, 0):
        return ()

    records: list[tuple[int, int, int, int, int]] = []
    offset = 0
    raw = buffer.raw
    while offset + 8 <= required.value:
        size, info_type = struct.unpack_from("<II", raw, offset)
        if size < 20 or offset + size > required.value:
            break
        if info_type == 0:  # CpuSetInformation
            cpu_set_id = struct.unpack_from("<I", raw, offset + 8)[0]
            group = struct.unpack_from("<H", raw, offset + 12)[0]
            logical_index = raw[offset + 14]
            core_index = raw[offset + 15]
            efficiency_class = raw[offset + 18]
            flags = raw[offset + 19]
            parked = bool(flags & 0x01)
            allocated_elsewhere = bool(flags & 0x02)
            if not parked and not allocated_elsewhere:
                records.append((cpu_set_id, group, logical_index, core_index, efficiency_class))
        offset += size

    return tuple(records)


@lru_cache(maxsize=1)
def preferred_windows_cpu_sets() -> tuple[int, ...]:
    """Return the shared E-core-first CPU Set IDs selected for this machine."""
    topology = _windows_cpu_topology()
    records = [(cpu_set_id, core_index, efficiency)
               for cpu_set_id, _group, _logical, core_index, efficiency in topology]
    return _select_cpu_sets(records, min(allowed_cpu_count(), len(records)))


def _preferred_windows_affinity_mask() -> int:
    """Hard affinity mask matching the selected CPU Sets when they share a group."""
    selected = set(preferred_windows_cpu_sets())
    chosen = [record for record in _windows_cpu_topology() if record[0] in selected]
    if not chosen or len({record[1] for record in chosen}) != 1:
        return 0
    return sum(1 << record[2] for record in chosen)


def apply_cpu_limit(process_handle=None) -> bool:
    """Constrain this process, or a Windows child handle, to the shared CPU set."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        handle = process_handle if process_handle is not None else kernel32.GetCurrentProcess()

        cpu_sets = preferred_windows_cpu_sets()
        set_cpu_sets = getattr(kernel32, "SetProcessDefaultCpuSets", None)
        cpu_sets_applied = False
        if cpu_sets and set_cpu_sets is not None:
            set_cpu_sets.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG), wintypes.ULONG]
            set_cpu_sets.restype = wintypes.BOOL
            ids = (wintypes.ULONG * len(cpu_sets))(*cpu_sets)
            cpu_sets_applied = bool(set_cpu_sets(wintypes.HANDLE(handle), ids, len(cpu_sets)))

        # Fallback for Windows versions without CPU Sets. This cannot identify
        # hybrid-core classes, but still enforces the same hard 50% ceiling.
        kernel32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        kernel32.SetProcessAffinityMask.restype = wintypes.BOOL

        # A Windows processor-group affinity mask is pointer-sized. On machines
        # with more CPUs this remains stricter than the requested 50% ceiling.
        mask_width = ctypes.sizeof(ctypes.c_size_t) * 8
        mask = _preferred_windows_affinity_mask()
        if not mask:
            fallback_ids = tuple(i for i in allowed_cpu_ids() if i < mask_width)
            mask = sum(1 << cpu_id for cpu_id in fallback_ids)
        affinity_applied = bool(kernel32.SetProcessAffinityMask(wintypes.HANDLE(handle), mask))
        return affinity_applied and (cpu_sets_applied or not cpu_sets)

    if process_handle is None and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, set(allowed_cpu_ids()))
            return True
        except OSError:
            return False
    return False


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

    budget = allowed_cpu_count(logical)
    per = max(1, min(16, budget // renders))

    return {
        "filter_threads": per,
        "encoder_threads": per,
        "decoder_threads": per,
    }
