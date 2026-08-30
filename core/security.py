"""
Client-side security primitives for the EncoMie license system.

Phase 1 security model
----------------------
* Requests to the license server are signed with a shared HMAC secret
  (``_REQUEST_HMAC_SECRET``). This is obfuscated in the binary but is NOT the
  primary defence - a determined reverser can recover it. Its job is to stop
  casual request tampering and, together with a per-request nonce + timestamp,
  to make replay useless.
* Server responses are delivered as an **Ed25519-signed license token**. The
  client only holds the *public* key (``_LICENSE_PUBLIC_KEY_B64``), so a
  recovered client cannot forge a server response or run a fake license server.
* The token's ``exp`` claim (absolute UTC ms) is the single source of truth for
  how long the app may run offline. There is no separate grace-period clock
  arithmetic any more, which removes the clock-rollback attack surface.
"""

import os
import sys
import json
import time
import hmac
import base64
import hashlib
import winreg
import subprocess
import ctypes
from pathlib import Path
from typing import Optional, Dict, Any

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

# ---------------------------------------------------------------------------
# Keys / secrets
# ---------------------------------------------------------------------------

# Shared HMAC secret for signing client -> server requests.
# XOR-obfuscated only to keep it out of a plain `strings` dump. Treat as public
# to a skilled attacker; the real trust anchor is the Ed25519 public key below.
_OBSCURED_REQUEST_SECRET = bytes([
    # production REQUEST_HMAC_SECRET xor 0x5A (regenerate via scripts/obfuscate_secret.py on key rotation)
    0x6f, 0x17, 0x29, 0x1b, 0x37, 0x2f, 0x37, 0x1e, 0x15, 0x0b, 0x71, 0x6f, 0x62, 0x28, 0x15, 0x22,
    0x12, 0x38, 0x69, 0x0d, 0x2e, 0x6c, 0x12, 0x63, 0x31, 0x03, 0x0f, 0x6d, 0x14, 0x29, 0x2b, 0x36,
    0x23, 0x16, 0x2a, 0x6f, 0x16, 0x14, 0x28, 0x71, 0x75, 0x0d, 0x17, 0x67,
])
_REQUEST_SECRET_XOR_KEY = 0x5A

# Ed25519 public key (raw 32 bytes, base64) matching the server's
# LICENSE_PRIVATE_KEY. Safe to ship. Replace on key rotation.
_LICENSE_PUBLIC_KEY_B64 = "UPtPFh7vrp+pKatFCw4ktlA4YEZyOayMwjqdD/6Ydb8="


def _request_hmac_secret() -> str:
    env = os.environ.get("ENCOMIE_REQUEST_SECRET")
    if env:
        return env
    return "".join(chr(b ^ _REQUEST_SECRET_XOR_KEY) for b in _OBSCURED_REQUEST_SECRET)


REQUEST_HMAC_SECRET = _request_hmac_secret()

_VERIFY_KEY = VerifyKey(base64.b64decode(_LICENSE_PUBLIC_KEY_B64))


# ---------------------------------------------------------------------------
# Active anti-tamper checks (soft signals - reported, not fatal on their own)
# ---------------------------------------------------------------------------

BLACK_LISTED_PROCESSES = {
    "x64dbg.exe", "x32dbg.exe", "cheatengine-x86_64.exe", "cheatengine.exe",
    "fiddler.exe", "charles.exe", "wireshark.exe", "processhacker.exe",
    "frida-server.exe", "ida.exe", "ida64.exe", "dnspy.exe", "httpdebugger.exe",
}


def is_debugger_present() -> bool:
    """Check if a debugger is currently attached using the Win32 API."""
    if not sys.platform.startswith("win"):
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        if kernel32.IsDebuggerPresent() != 0:
            return True
        is_remote_present = ctypes.c_bool(False)
        if kernel32.CheckRemoteDebuggerPresent(kernel32.GetCurrentProcess(), ctypes.byref(is_remote_present)):
            if is_remote_present.value:
                return True
    except Exception:
        pass
    return False


def scan_suspicious_processes() -> Optional[str]:
    """Scan running processes for known cracking / proxy / debugging tools."""
    if not sys.platform.startswith("win"):
        return None
    try:
        output = subprocess.check_output(
            "tasklist /NH /FO CSV",
            shell=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True,
            errors="ignore",
        )
        for line in output.splitlines():
            parts = line.split('","')
            if parts:
                p_name = parts[0].replace('"', "").strip().lower()
                if p_name in BLACK_LISTED_PROCESSES:
                    return p_name
    except Exception:
        pass
    return None


def get_windows_machine_guid() -> str:
    """Read the un-spoofable Windows Registry MachineGuid."""
    if not sys.platform.startswith("win"):
        return "non_windows_system"
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return str(guid)
    except Exception:
        return "fallback_guid"


def detect_vm() -> Optional[str]:
    """Best-effort detection of a virtual machine environment (soft signal only)."""
    if not sys.platform.startswith("win"):
        return None
    try:
        output = subprocess.check_output(
            "wmic bios get serialnumber /format:csv",
            shell=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True,
            errors="ignore",
        ).lower()
        if any(term in output for term in ["vbox", "vmware", "qemu", "virtualbox", "hyper-v"]):
            return "Virtual Machine Environment Detected"
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Request signing (client -> server)
# ---------------------------------------------------------------------------

def compute_hmac_signature(payload_string: str, secret: str = REQUEST_HMAC_SECRET) -> str:
    """HMAC-SHA256 hex signature of a request payload string."""
    sec = (secret or REQUEST_HMAC_SECRET).encode("utf-8")
    return hmac.new(sec, payload_string.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_nonce() -> str:
    """32-byte random hex nonce for anti-replay protection."""
    return os.urandom(32).hex()


# ---------------------------------------------------------------------------
# License token verification (server -> client)
# ---------------------------------------------------------------------------

def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_license_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify an Ed25519-signed license token and return its claims dict, or None
    if the signature is invalid or the token is malformed.

    Callers must still check ``exp``, ``machine_id`` and ``status`` themselves.
    """
    try:
        body_b64, sig_b64 = token.split(".", 1)
    except (ValueError, AttributeError):
        return None
    try:
        _VERIFY_KEY.verify(body_b64.encode("ascii"), _b64url_decode(sig_b64))
    except (BadSignatureError, Exception):
        return None
    try:
        claims = json.loads(_b64url_decode(body_b64))
        return claims if isinstance(claims, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Local cache integrity (secondary - the token itself is tamper-evident)
# ---------------------------------------------------------------------------

def compute_cache_hmac(key: str, machine_id: str, saved_at: str, data_str: str = "",
                       secret: str = REQUEST_HMAC_SECRET) -> str:
    """HMAC over the local license cache to detect casual hand-editing."""
    payload = f"{key}|{machine_id}|{saved_at}|{data_str}"
    return compute_hmac_signature(payload, secret or REQUEST_HMAC_SECRET)


def compute_file_sha256(filepath: Path) -> str:
    """SHA-256 of a file for code-integrity checks."""
    if not filepath.exists():
        return ""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
