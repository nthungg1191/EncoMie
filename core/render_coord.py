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

# Machine-wide CPU budget fractions by dynamic workload mode:
#   - turbo    (1 active render): up to 65% of logical CPUs, P-core-first (still protects Core 0)
#   - balanced (2 active renders): 50% of logical CPUs, E-core-first + high P-cores
#   - eco      (>=3 active renders): 50% of logical CPUs, E-core-first + IDLE priority + Low I/O
CPU_BUDGET_FRACTION = 0.5
TURBO_CPU_BUDGET_FRACTION = 0.65

WIN_IDLE_PRIORITY_CLASS = 0x00000040
WIN_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
IO_PRIORITY_LOW = 1
IO_PRIORITY_NORMAL = 2


def resolve_render_mode(total_renders: int) -> str:
    """Classify machine-wide render concurrency into a dynamic resource profile."""
    n = max(1, int(total_renders or 1))
    if n == 1:
        return "turbo"
    if n == 2:
        return "balanced"
    return "eco"

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


def allowed_cpu_count(logical: int | None = None, mode: str = "eco") -> int:
    """Maximum logical CPUs shared by all instances for the given mode."""
    total = max(1, int(logical if logical is not None else (os.cpu_count() or 1)))
    if mode == "turbo":
        # Protect at least 1 physical core (typically 2 logical threads on SMT)
        return max(1, min(total - 1 if total >= 2 else 1, int(total * TURBO_CPU_BUDGET_FRACTION)))
    return max(1, int(total * CPU_BUDGET_FRACTION))


def allowed_cpu_ids(logical: int | None = None, mode: str = "eco") -> tuple[int, ...]:
    """Fallback CPU indices when Windows CPU topology is unavailable."""
    total = max(1, int(logical if logical is not None else (os.cpu_count() or 1)))
    count = allowed_cpu_count(total, mode=mode)
    return tuple(range(total - count, total))


def _select_cpu_sets(records: list[tuple[int, int, int]], count: int, mode: str = "eco") -> tuple[int, ...]:
    """Choose CPU Set IDs adaptively across all CPU architectures and modes.

    Each record is ``(cpu_set_id, core_index, efficiency_class)``. Windows uses
    a larger EfficiencyClass for faster P-cores and smaller (e.g. 0) for
    efficient E-cores.

    Strategy:
      1. Hybrid CPUs (>= 2 efficiency classes, e.g. Intel 12/13/14th Gen):
         - ``turbo`` (1 active render): protect Core 0 (first P-core) for OS/UI,
           then pick high-speed P-cores FIRST (from highest-index down to Core 1)
           for maximum single-job FPS, then fill remaining budget with E-cores.
         - ``balanced`` / ``eco`` (>= 2 active renders): take all E-cores first
           (ascending efficiency class), then borrow from highest-index P-cores
           while strictly protecting the first 2 P-cores (Core 0 & Core 1).
      2. Symmetric CPUs (1 efficiency class, e.g. AMD Ryzen, older Intel, Xeon):
         - ``turbo``: protect Core 0 (when physical_cores >= 2), pick from
           highest-index cores first (distinct physical cores before SMT).
         - ``balanced`` / ``eco``: protect Core 0 & Core 1 (when physical_cores >= 8)
           or Core 0 (when physical_cores >= 2), pick from highest-index cores.
    """
    if not records or count <= 0:
        return ()

    efficiencies = sorted({record[2] for record in records})
    is_hybrid = len(efficiencies) >= 2
    selected: list[int] = []

    def _pick_from_tier(tier_records: list[tuple[int, int, int]], reverse_cores: bool) -> None:
        ordered = sorted(
            tier_records,
            key=lambda r: (-r[1] if reverse_cores else r[1], r[0]),
        )
        seen_cores: set[int] = set()
        for cpu_set_id, core_index, _ in ordered:
            if core_index not in seen_cores:
                selected.append(cpu_set_id)
                seen_cores.add(core_index)
                if len(selected) == count:
                    return
        for cpu_set_id, _core_index, _ in ordered:
            if cpu_set_id not in selected:
                selected.append(cpu_set_id)
                if len(selected) == count:
                    return

    if is_hybrid:
        highest_eff = efficiencies[-1]
        p_tier = [r for r in records if r[2] == highest_eff]
        p_cores = sorted({r[1] for r in p_tier})

        if mode == "turbo":
            # Protect Core 0 (first P-core) for OS/UI; give P-cores first for max speed
            reserve_p = 1 if len(p_cores) >= 2 else 0
            allowed_p_cores = set(p_cores[reserve_p:])
            fast_p = [r for r in p_tier if r[1] in allowed_p_cores]
            if fast_p:
                _pick_from_tier(fast_p, reverse_cores=True)
                if len(selected) == count:
                    return tuple(selected)
            for eff in reversed(efficiencies[:-1]):
                tier = [r for r in records if r[2] == eff]
                _pick_from_tier(tier, reverse_cores=False)
                if len(selected) == count:
                    return tuple(selected)
            return tuple(selected)

        # balanced / eco: E-cores first, protect first 2 P-cores
        for eff in efficiencies[:-1]:
            tier = [r for r in records if r[2] == eff]
            _pick_from_tier(tier, reverse_cores=False)
            if len(selected) == count:
                return tuple(selected)

        reserve_p = 2 if len(p_cores) >= 4 else (1 if len(p_cores) >= 2 else 0)
        allowed_p_cores = set(p_cores[reserve_p:])
        borrowable = [r for r in p_tier if r[1] in allowed_p_cores]
        if borrowable:
            _pick_from_tier(borrowable, reverse_cores=True)
        return tuple(selected)

    # Symmetric CPU (single efficiency class)
    phys_cores = sorted({r[1] for r in records})
    if mode == "turbo":
        reserve = 1 if len(phys_cores) >= 2 else 0
    else:
        reserve = 2 if len(phys_cores) >= 8 else (1 if len(phys_cores) >= 2 else 0)
    allowed_cores = set(phys_cores[reserve:])
    eligible = [r for r in records if r[1] in allowed_cores]
    _pick_from_tier(eligible, reverse_cores=True)
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
            allocated_elsewhere = bool(flags & 0x02)
            # Do NOT exclude temporarily parked cores (flags & 0x01): Windows
            # dynamically parks idle cores and wakes them on demand. Filtering
            # parked cores caused different EncoMie instances to pick different
            # CPU subsets and collectively exceed the 50% machine-wide ceiling.
            if not allocated_elsewhere:
                records.append((cpu_set_id, group, logical_index, core_index, efficiency_class))
        offset += size

    return tuple(records)


@lru_cache(maxsize=4)
def preferred_windows_cpu_sets(mode: str = "eco") -> tuple[int, ...]:
    """Return the shared CPU Set IDs selected for this machine and mode."""
    topology = _windows_cpu_topology()
    records = [(cpu_set_id, core_index, efficiency)
               for cpu_set_id, _group, _logical, core_index, efficiency in topology]
    return _select_cpu_sets(records, min(allowed_cpu_count(mode=mode), len(records)), mode=mode)


def _preferred_windows_affinity_mask(mode: str = "eco") -> int:
    """Hard affinity mask matching the selected CPU Sets when they share a group."""
    selected = set(preferred_windows_cpu_sets(mode))
    chosen = [record for record in _windows_cpu_topology() if record[0] in selected]
    if not chosen or len({record[1] for record in chosen}) != 1:
        return 0
    return sum(1 << record[2] for record in chosen)


def apply_cpu_limit(process_handle=None, mode: str = "eco") -> bool:
    """Constrain this process, or a Windows child handle, to the mode's CPU set."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        handle = process_handle if process_handle is not None else kernel32.GetCurrentProcess()

        cpu_sets = preferred_windows_cpu_sets(mode)
        set_cpu_sets = getattr(kernel32, "SetProcessDefaultCpuSets", None)
        cpu_sets_applied = False
        if cpu_sets and set_cpu_sets is not None:
            set_cpu_sets.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG), wintypes.ULONG]
            set_cpu_sets.restype = wintypes.BOOL
            ids = (wintypes.ULONG * len(cpu_sets))(*cpu_sets)
            cpu_sets_applied = bool(set_cpu_sets(wintypes.HANDLE(handle), ids, len(cpu_sets)))

        kernel32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        kernel32.SetProcessAffinityMask.restype = wintypes.BOOL

        mask_width = ctypes.sizeof(ctypes.c_size_t) * 8
        mask = _preferred_windows_affinity_mask(mode)
        if not mask:
            fallback_ids = tuple(i for i in allowed_cpu_ids(mode=mode) if i < mask_width)
            mask = sum(1 << cpu_id for cpu_id in fallback_ids)
        affinity_applied = bool(kernel32.SetProcessAffinityMask(wintypes.HANDLE(handle), mask))
        return affinity_applied and (cpu_sets_applied or not cpu_sets)

    if process_handle is None and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, set(allowed_cpu_ids(mode=mode)))
            return True
        except OSError:
            return False
    return False


def apply_process_priority(process_handle, priority_class: int) -> bool:
    """Update CPU priority class of a running Windows child process."""
    if sys.platform != "win32" or not process_handle:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        return bool(kernel32.SetPriorityClass(wintypes.HANDLE(process_handle), priority_class))
    except Exception:
        return False


def apply_background_io_priority(process_handle, io_priority: int = IO_PRIORITY_LOW) -> bool:
    """Set Disk I/O priority of a Windows child process (ffmpeg.exe) via
    NtSetInformationProcess(ProcessIoPriority=33): 1=Low, 2=Normal.
    Best-effort: returns False silently if the OS denies the call.
    """
    if sys.platform != "win32" or not process_handle:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        ntdll = ctypes.WinDLL("ntdll")
        nt_set = getattr(ntdll, "NtSetInformationProcess", None)
        if nt_set is None:
            return False
        nt_set.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
        nt_set.restype = ctypes.c_long
        PROCESS_IO_PRIORITY = 33
        val = ctypes.c_ulong(int(io_priority))
        status = nt_set(
            wintypes.HANDLE(process_handle),
            PROCESS_IO_PRIORITY,
            ctypes.byref(val),
            ctypes.sizeof(val),
        )
        return status == 0
    except Exception:
        return False


def apply_render_profile(process_handle, total_renders: int) -> str:
    """Apply or live-rebalance CPU Affinity, CPU Priority, and Disk I/O Priority
    on a running ffmpeg.exe process according to machine-wide active render count.
    Returns the applied mode ('turbo', 'balanced', or 'eco').
    """
    mode = resolve_render_mode(total_renders)
    if not apply_cpu_limit(process_handle, mode=mode):
        raise RuntimeError(f"Không thể áp dụng giới hạn CPU ({mode}) cho FFmpeg")
    if mode == "eco":
        apply_process_priority(process_handle, WIN_IDLE_PRIORITY_CLASS)
        apply_background_io_priority(process_handle, IO_PRIORITY_LOW)
    else:
        apply_process_priority(process_handle, WIN_BELOW_NORMAL_PRIORITY_CLASS)
        apply_background_io_priority(process_handle, IO_PRIORITY_NORMAL)
    return mode


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
    Dynamic per-render thread budget and profile across all EncoMie instances.
    Call this AFTER entering a RenderSlot so the count includes this render.
    """
    logical = os.cpu_count() or 4
    renders = max(active_render_count(), 1, int(max_concurrent_this_instance or 1))
    mode = resolve_render_mode(renders)

    budget = allowed_cpu_count(logical, mode=mode)
    per = max(1, min(16, budget // renders))
    if mode == "turbo":
        dec_cap = min(4, per)
    elif mode == "balanced":
        dec_cap = min(3, per)
    else:
        dec_cap = min(2, per)

    return {
        "mode": mode,
        "renders": renders,
        "filter_threads": per,
        "encoder_threads": per,
        "decoder_threads": max(1, dec_cap),
    }
