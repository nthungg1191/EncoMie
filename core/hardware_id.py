"""
core/hardware_id.py
Định danh phần cứng bền vững (Hardware-based HWID) cho Windows 10/11.
Khắc phục triệt để lỗi reset Machine ID khi Windows 11 cập nhật hoặc đổi mạng/VPN.
Hỗ trợ tương thích ngược 100% với các máy Windows 10 đã kích hoạt trước đó.
"""

import sys
import ctypes
from ctypes import wintypes
import struct
import hashlib
import winreg
import subprocess
import platform
import uuid
from typing import Optional, Dict


def get_smbios_uuid() -> Optional[str]:
    """
    Đọc UUID của bo mạch chủ trực tiếp từ SMBIOS Firmware Table qua Win32 API.
    - Hỗ trợ: Windows Vista, 7, 8, 10, 11 (32-bit & 64-bit).
    - Tốc độ: ~0.1 ms (siêu nhanh, không tạo tiến trình con).
    - Không phụ thuộc wmic.exe (hoạt động 100% trên Windows 11 24H2+).
    - Bất biến qua mọi bản cập nhật Windows Update hoặc cài lại Windows.
    """
    if not sys.platform.startswith("win"):
        return None

    # Cách 1: Native Win32 API GetSystemFirmwareTable (nhanh nhất & chính xác nhất)
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        GetSystemFirmwareTable = kernel32.GetSystemFirmwareTable
        GetSystemFirmwareTable.restype = wintypes.UINT
        GetSystemFirmwareTable.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.UINT]

        sig = struct.unpack(">I", b"RSMB")[0]
        size = GetSystemFirmwareTable(sig, 0, None, 0)
        if size > 0:
            buf = ctypes.create_string_buffer(size)
            GetSystemFirmwareTable(sig, 0, buf, size)
            raw = bytes(buf.raw)

            offset = 8
            while offset < len(raw) - 4:
                header_type = raw[offset]
                header_len = raw[offset + 1]
                if header_type == 1 and header_len >= 0x18:
                    uuid_bytes = raw[offset + 8 : offset + 24]
                    # Bỏ qua UUID không hợp lệ (tất cả 0 hoặc tất cả FF)
                    if uuid_bytes not in (b"\x00" * 16, b"\xff" * 16):
                        p1 = uuid_bytes[0:4][::-1].hex()
                        p2 = uuid_bytes[4:6][::-1].hex()
                        p3 = uuid_bytes[6:8][::-1].hex()
                        p4 = uuid_bytes[8:10].hex()
                        p5 = uuid_bytes[10:16].hex()
                        res = f"{p1}-{p2}-{p3}-{p4}-{p5}".upper()
                        if len(res) == 36:
                            return res
                    break

                # Nhảy qua string table (kết thúc bằng 2 null bytes)
                idx = offset + header_len
                while idx < len(raw) - 1 and not (raw[idx] == 0 and raw[idx + 1] == 0):
                    idx += 1
                offset = idx + 2
    except Exception:
        pass

    # Cách 2: Fallback an toàn qua PowerShell CIM (chỉ gọi nếu Native API gặp bo mạch đặc thù)
    try:
        ps_cmd = "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID"
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=3,
            errors="ignore",
        ).strip().upper()
        if out and len(out) == 36 and not out.startswith("00000000"):
            return out
    except Exception:
        pass

    return None


def get_bios_hardware_info() -> Dict[str, str]:
    """
    Đọc thông tin bo mạch chủ từ Registry HARDWARE (được kernel dựng lúc boot).
    Cực nhanh (<0.01ms), không bị ảnh hưởng bởi Windows Update.
    """
    info = {
        "board_product": "unknown_product",
        "board_vendor": "unknown_vendor",
        "system_product": "unknown_sys",
    }
    if not sys.platform.startswith("win"):
        return info

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as key:
            for reg_name, dict_key in [
                ("BaseBoardProduct", "board_product"),
                ("BaseBoardManufacturer", "board_vendor"),
                ("SystemProductName", "system_product"),
            ]:
                try:
                    val, _ = winreg.QueryValueEx(key, reg_name)
                    if val and str(val).strip():
                        info[dict_key] = str(val).strip()
                except Exception:
                    pass
    except Exception:
        pass
    return info


def get_cpu_hardware_info() -> str:
    """Lấy thông tin CPU Identifier từ Registry HARDWARE."""
    if not sys.platform.startswith("win"):
        return platform.processor() or "unknown_cpu"

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            ident, _ = winreg.QueryValueEx(key, "Identifier")
            return str(ident).strip()
    except Exception:
        return platform.processor() or "fallback_cpu"


def get_system_volume_serial() -> str:
    """Lấy Volume Serial Number của ổ C (nơi cài đặt Windows)."""
    if not sys.platform.startswith("win"):
        return "non_windows_drive"

    try:
        vol_serial = ctypes.c_ulong()
        ret = ctypes.windll.kernel32.GetVolumeInformationW(
            "C:\\", None, 0, ctypes.byref(vol_serial), None, None, None, 0
        )
        if ret != 0:
            return f"{vol_serial.value:08X}"
    except Exception:
        pass
    return "default_vol_serial"


def get_stable_machine_id() -> str:
    """
    Tạo 32-ký tự Machine ID bền vững (HWID v2):
    - Độc lập hoàn toàn với Network (loại bỏ MAC & Random MAC trên Win 11).
    - Độc lập hoàn toàn với Windows Update (loại bỏ MachineGuid & Computer Name).
    - Bất biến dựa trên phần cứng vật lý (Motherboard UUID + Board Model + CPU + Volume Serial).
    """
    smbios_uuid = get_smbios_uuid() or "ENCOMIE_SMBIOS_NONE"
    bios_info = get_bios_hardware_info()
    cpu_info = get_cpu_hardware_info()
    vol_serial = get_system_volume_serial()

    raw_parts = [
        smbios_uuid,
        bios_info["board_product"],
        bios_info["board_vendor"],
        bios_info["system_product"],
        cpu_info,
        vol_serial,
    ]
    raw_str = "|".join(raw_parts)
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:32]


def get_legacy_machine_id() -> str:
    """
    Thuật toán Machine ID cũ (HWID v1) để tương thích ngược cho các máy Win 10 cũ đã kích hoạt.
    """
    from core.security import get_windows_machine_guid
    try:
        comps = {
            "machine_guid": get_windows_machine_guid(),
            "node": platform.node(),
            "arch": platform.machine(),
            "cpu": platform.processor(),
            "mac": str(uuid.getnode()),
        }
        raw_id = "|".join(comps[k] for k in ("machine_guid", "node", "arch", "cpu", "mac"))
        return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:32]
    except Exception:
        return hashlib.sha256(b"encomie_fallback_hwid").hexdigest()[:32]
