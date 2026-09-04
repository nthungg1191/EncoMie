"""Utility: detect NVIDIA GPU, NVENC support, and system resources via FFmpeg / nvidia-smi."""

import subprocess
import re
from pathlib import Path

import sys

# Local bin path detection
if getattr(sys, 'frozen', False):
    exe_bin_dir = Path(sys.executable).parent / "bin"
    if (exe_bin_dir / "ffmpeg.exe").exists():
        LOCAL_BIN_DIR = exe_bin_dir
    else:
        LOCAL_BIN_DIR = Path(__file__).parent.parent / "bin"
else:
    LOCAL_BIN_DIR = Path(__file__).parent.parent / "bin"

FFMPEG_PATH = str(LOCAL_BIN_DIR / "ffmpeg.exe") if (LOCAL_BIN_DIR / "ffmpeg.exe").exists() else "ffmpeg"
FFPROBE_PATH = str(LOCAL_BIN_DIR / "ffprobe.exe") if (LOCAL_BIN_DIR / "ffprobe.exe").exists() else "ffprobe"


def detect_gpu() -> dict:
    """
    Returns dict with keys:
      - available (bool)
      - name (str)
      - nvenc_h264 (bool)
      - nvenc_hevc (bool)
    """
    info = {"available": False, "name": "Không tìm thấy GPU", "nvenc_h264": False, "nvenc_hevc": False}

    # Check nvidia-smi
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, encoding="utf-8", errors="replace", timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            info["available"] = True
            info["name"] = r.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass

    # Check FFmpeg NVENC encoders
    try:
        r = subprocess.run([FFMPEG_PATH, "-encoders"], capture_output=True, encoding="utf-8", errors="replace", timeout=10)
        out = r.stdout + r.stderr
        if "h264_nvenc" in out:
            info["nvenc_h264"] = True
        if "hevc_nvenc" in out:
            info["nvenc_hevc"] = True
    except Exception:
        pass

    return info


def check_ffmpeg() -> bool:
    try:
        subprocess.run([FFMPEG_PATH, "-version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def check_ffprobe() -> bool:
    try:
        subprocess.run([FFPROBE_PATH, "-version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


_CPU_NAME_CACHE = None
_CPU_TICKS_CACHE = None  # (idle, kernel, user) from the previous GetSystemTimes call


def _cpu_name() -> str:
    """Processor name from the registry (instant, no subprocess). Cached."""
    global _CPU_NAME_CACHE
    if _CPU_NAME_CACHE is not None:
        return _CPU_NAME_CACHE
    name = "—"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            name = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
    except Exception:
        pass
    _CPU_NAME_CACHE = name
    return name


def _cpu_load_pct() -> int:
    """System-wide CPU load via GetSystemTimes deltas (µs, no subprocess)."""
    global _CPU_TICKS_CACHE
    try:
        import ctypes
        from ctypes import wintypes

        idle = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return 0

        def _u64(ft):
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

        cur = (_u64(idle), _u64(kernel), _u64(user))
        if _CPU_TICKS_CACHE is None:
            _CPU_TICKS_CACHE = cur
            return 0
        di = cur[0] - _CPU_TICKS_CACHE[0]
        dk = cur[1] - _CPU_TICKS_CACHE[1]
        du = cur[2] - _CPU_TICKS_CACHE[2]
        _CPU_TICKS_CACHE = cur
        total = dk + du  # kernel time already includes idle
        if total <= 0:
            return 0
        return max(0, min(100, int(round((1 - di / total) * 100))))
    except Exception:
        return 0


def _ram_info() -> tuple[float, float, int]:
    """(total_gb, free_gb, used_pct) via GlobalMemoryStatusEx (instant)."""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return 0.0, 0.0, 0
        gb = 1024 ** 3
        return (round(m.ullTotalPhys / gb, 1),
                round(m.ullAvailPhys / gb, 1),
                int(m.dwMemoryLoad))
    except Exception:
        return 0.0, 0.0, 0


def detect_system_info() -> dict:
    """
    Live system metrics. CPU + RAM come from Win32 calls (microseconds); only
    GPU stats still shell out to nvidia-smi. Safe to call on a background thread
    every few seconds — NOT on the UI thread on a hot timer.

    Keys: cpu_name, cpu_load_pct, ram_total_gb, ram_free_gb, ram_used_pct,
          gpu_name, gpu_available, vram_total_mb, vram_free_mb, gpu_power_w
    """
    ram_total, ram_free, ram_pct = _ram_info()
    info = {
        "cpu_name": _cpu_name(),
        "cpu_load_pct": _cpu_load_pct(),
        "ram_total_gb": ram_total,
        "ram_free_gb": ram_free,
        "ram_used_pct": ram_pct,
        "gpu_name": "Khong co GPU",
        "gpu_available": False,
        "vram_total_mb": 0,
        "vram_free_mb": 0,
        "gpu_power_w": "—",
    }

    # GPU via nvidia-smi (CSV: name, vram_total_MB, vram_free_MB, power_W)
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,memory.free,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = [p.strip() for p in r.stdout.strip().split(",")]
            info["gpu_available"] = True
            info["gpu_name"] = parts[0]
            if len(parts) >= 4:
                info["vram_total_mb"] = int(parts[1])
                info["vram_free_mb"] = int(parts[2])
                info["gpu_power_w"] = parts[3] + " W"
            elif len(parts) >= 2:
                info["vram_total_mb"] = int(parts[1])
    except Exception:
        pass

    return info
