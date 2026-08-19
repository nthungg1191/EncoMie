
import os
import sys
import time
import hmac
import hashlib
import winreg
import subprocess
import ctypes
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List

# XOR Byte Obfuscated secret key to prevent plaintext string extraction via reverse engineering tools
_OBSCURED_SECRET_BYTES = bytes([
    38, 45, 32, 44, 46, 42, 38, 110, 43, 46, 34, 32, 110, 48, 38, 49, 53, 38, 49, 110, 48, 38, 32, 49, 38, 55, 110, 40, 38, 58, 110, 113, 115, 113, 117
])
_SECRET_XOR_KEY = 0x43

def get_shared_security_secret() -> str:
    """Dynamically reconstruct shared HMAC secret at runtime."""
    env_secret = os.environ.get("SERVER_SECRET")
    if env_secret:
        return env_secret
    return "".join(chr(b ^ _SECRET_XOR_KEY) for b in _OBSCURED_SECRET_BYTES)

SHARED_SECURITY_SECRET = get_shared_security_secret()

# Blacklisted process names commonly used for cracking/interception
BLACK_LISTED_PROCESSES = {
    "x64dbg.exe", "x32dbg.exe", "cheatengine-x86_64.exe", "cheatengine.exe",
    "fiddler.exe", "charles.exe", "wireshark.exe", "processhacker.exe",
    "frida-server.exe", "ida.exe", "ida64.exe", "dnspy.exe", "httpdebugger.exe"
}


def is_debugger_present() -> bool:
    """
    Check if a debugger is currently attached using Win32 API.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        if kernel32.IsDebuggerPresent() != 0:
            return True
        
        is_remote_present = ctypes.c_bool(False)
        process_handle = kernel32.GetCurrentProcess()
        if kernel32.CheckRemoteDebuggerPresent(process_handle, ctypes.byref(is_remote_present)):
            if is_remote_present.value:
                return True
    except Exception:
        pass
    return False


def scan_suspicious_processes() -> Optional[str]:
    """
    Scan active system process names for cracking, proxy, or debugging tools.
    Returns process name if detected, otherwise None.
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        output = subprocess.check_output(
            "tasklist /NH /FO CSV",
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            text=True,
            errors="ignore"
        )
        for line in output.splitlines():
            parts = line.split('","')
            if parts:
                p_name = parts[0].replace('"', '').strip().lower()
                if p_name in BLACK_LISTED_PROCESSES:
                    return p_name
    except Exception:
        pass
    return None


def get_windows_machine_guid() -> str:
    """
    Read Windows Registry MachineGuid (un-spoofable system hardware key).
    """
    if not sys.platform.startswith("win"):
        return "non_windows_system"
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        )
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return str(guid)
    except Exception:
        return "fallback_guid"


def detect_vm() -> Optional[str]:
    """
    Detect if the application is running inside a cloned Virtual Machine (VMware, VirtualBox, QEMU, Hyper-V).
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        output = subprocess.check_output(
            "wmic bios get serialnumber /format:csv",
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            text=True,
            errors="ignore"
        ).lower()
        if any(term in output for term in ["vbox", "vmware", "qemu", "virtualbox", "hyper-v"]):
            return "Virtual Machine Environment Detected"
    except Exception:
        pass
    return None


def detect_clock_tampering(last_verified_iso: Optional[str]) -> bool:
    """
    Detect if user manipulated system clock backwards to extend offline grace period.
    Returns True if system clock was rolled back.
    """
    if not last_verified_iso:
        return False
    try:
        last_verified = datetime.fromisoformat(last_verified_iso.replace("Z", "+00:00"))
        now = datetime.now(last_verified.tzinfo) if last_verified.tzinfo else datetime.now()
        
        # If current system time is earlier than last verified timestamp by > 5 minutes, clock was tampered!
        if now < (last_verified - timedelta(minutes=5)):
            print("[Security] Clock rollback detected! Current system time is behind last verification.")
            return True
    except Exception as e:
        print(f"[Security] Clock check error: {e}")
    return False


def compute_hmac_signature(payload_string: str, secret: str = SHARED_SECURITY_SECRET) -> str:
    """
    Compute HMAC-SHA256 signature for payload string.
    """
    return hmac.new(secret.encode('utf-8'), payload_string.encode('utf-8'), hashlib.sha256).hexdigest()


def verify_server_response_signature(
    key: str,
    status_or_valid: Any,
    timestamp: int,
    signature: str,
    secret: str = SHARED_SECURITY_SECRET
) -> bool:
    """
    Verify server response signature to prevent MitM proxy response spoofing (e.g. Fiddler returning fake valid).
    """
    if not signature or not timestamp:
        return False
    
    # Verify 5-minute window
    now_ms = int(time.time() * 1000)
    if abs(now_ms - timestamp) > 300000:
        print("[Security] Server response timestamp outside allowed window")
        return False

    val_str = "true" if status_or_valid is True else ("false" if status_or_valid is False else str(status_or_valid))
    expected_payload = f"{key}|{val_str}|{timestamp}"
    expected_sig = compute_hmac_signature(expected_payload, secret)
    
    is_match = hmac.compare_digest(expected_sig.lower(), signature.lower())
    if not is_match:
        print(f"[Security] Warning: HMAC signature mismatch! Expected payload: '{expected_payload}', sig: '{expected_sig}', got: '{signature}'")
    return is_match


def compute_cache_hmac(key: str, machine_id: str, saved_at: str, secret: str = SHARED_SECURITY_SECRET) -> str:
    """
    Compute HMAC signature for protecting local license.json file against manual editing/tampering.
    """
    payload = f"{key}|{machine_id}|{saved_at}"
    return compute_hmac_signature(payload, secret)


def generate_nonce() -> str:
    """
    Generate a 16-byte random hexadecimal nonce for anti-replay protection.
    """
    return os.urandom(16).hex()


def compute_file_sha256(filepath: Path) -> str:
    """
    Compute SHA-256 hash of a file for code integrity verification.
    """
    if not filepath.exists():
        return ""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
