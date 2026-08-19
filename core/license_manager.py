"""
License Manager Module for EncoMie Desktop App.
Handles Machine HWID generation, server activation/verification API requests,
local encrypted cache storage, 7-day offline Grace Period support, and active security defenses.
"""

import os
import sys
import json
import time
import uuid
import hmac
import hashlib
import platform
import requests
from enum import Enum
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from core.security import (
    is_debugger_present,
    scan_suspicious_processes,
    get_windows_machine_guid,
    detect_clock_tampering,
    compute_hmac_signature,
    compute_cache_hmac,
    verify_server_response_signature,
    generate_nonce,
)


class LicenseStatus(Enum):
    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"
    REVOKED = "revoked"
    NOT_FOUND = "not_found"
    SERVER_ERROR = "server_error"
    SECURITY_VIOLATION = "security_violation"


@dataclass
class LicenseInfo:
    status: LicenseStatus
    key: str = ""
    machine_id: str = ""
    expires_at: Optional[datetime] = None
    last_verified: Optional[datetime] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.status == LicenseStatus.VALID


class LicenseManager:
    # Server API Base URL
    DEFAULT_API_URL = "https://encomie-server.19novemberrr.workers.dev"
    GRACE_PERIOD_DAYS = 1  # Maximum days allowed for offline usage

    def __init__(self, api_url: Optional[str] = None):
        raw_url = api_url or os.environ.get("LICENSE_API_URL", self.DEFAULT_API_URL)
        self.API_BASE_URL = raw_url.rstrip("/")
        self._machine_id = self.get_machine_id()
        self._cache_file = self._get_cache_filepath()

    @staticmethod
    def get_machine_id() -> str:
        """
        Generate a stable SHA-256 Hardware ID (HWID) based on hardware attributes and Registry GUID.
        """
        try:
            tokens = [
                get_windows_machine_guid(), # Windows Registry MachineGuid
                platform.node(),            # Hostname
                platform.machine(),         # CPU Architecture
                platform.processor(),       # Processor description
                str(uuid.getnode()),        # MAC Address integer
            ]
            raw_id = "|".join(tokens)
            return hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:32]
        except Exception:
            return hashlib.sha256(b"encomie_fallback_hwid").hexdigest()[:32]

    def _get_cache_filepath(self) -> Path:
        """
        Get the local filepath for license caching in AppData/User directory.
        """
        if sys.platform.startswith("win"):
            base_dir = Path(os.environ.get("APPDATA", Path.home())) / "EncoMie"
        else:
            base_dir = Path.home() / ".config" / "encomie"
        
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir / "license.json"

    def _save_cache(self, key: str, data: Dict[str, Any]):
        """
        Save license information to local cache file with HMAC integrity checksum.
        """
        try:
            saved_at = datetime.now().isoformat()
            cache_hmac = compute_cache_hmac(key, self._machine_id, saved_at)
            cache_payload = {
                "key": key,
                "machine_id": self._machine_id,
                "data": data,
                "saved_at": saved_at,
                "checksum": cache_hmac,
            }
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[LicenseManager] Warning: Failed to save cache: {e}")

    def _load_cache(self) -> Optional[Dict[str, Any]]:
        """
        Load cached license information from local disk and verify HMAC integrity checksum.
        """
        if not self._cache_file.exists():
            return None
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                payload = json.load(f)

            # Verify cache checksum against manual text editing / tampering
            key = payload.get("key", "")
            machine_id = payload.get("machine_id", "")
            saved_at = payload.get("saved_at", "")
            checksum = payload.get("checksum", "")

            expected_checksum = compute_cache_hmac(key, machine_id, saved_at)
            if not checksum or not hmac.compare_digest(expected_checksum, checksum):
                print("[Security] Warning: Local license.json cache checksum mismatch! File was manually edited.")
                self._clear_cache()
                return None

            return payload
        except Exception:
            return None

    def _clear_cache(self):
        """
        Remove local cached license file.
        """
        if self._cache_file.exists():
            try:
                self._cache_file.unlink()
            except Exception as e:
                print(f"[LicenseManager] Failed to clear cache: {e}")

    def _run_security_audit(self) -> Optional[LicenseInfo]:
        """
        Run active security checks (anti-debugging and process scanning).
        """
        if is_debugger_present():
            print("[Security] Active debugger detected via Win32 API!")
            return LicenseInfo(
                status=LicenseStatus.SECURITY_VIOLATION,
                raw_data={"error": {"message": "Debugger detected. App execution restricted."}}
            )
        
        suspicious_proc = scan_suspicious_processes()
        if suspicious_proc:
            print(f"[Security] Suspicious cracking/proxy tool detected: {suspicious_proc}")
            return LicenseInfo(
                status=LicenseStatus.SECURITY_VIOLATION,
                raw_data={"error": {"message": f"Security violation: Suspicious process '{suspicious_proc}' detected."}}
            )

        return None

    def activate(self, key: str) -> LicenseInfo:
        """
        Activate a license key on the current machine via API with HMAC signing.
        """
        sec_violation = self._run_security_audit()
        if sec_violation:
            return sec_violation

        clean_key = key.strip().upper()
        if not clean_key:
            return LicenseInfo(status=LicenseStatus.INVALID)

        timestamp = int(time.time() * 1000)
        nonce = generate_nonce()
        payload_str = f"{clean_key}|{self._machine_id}|{nonce}|{timestamp}"
        signature = compute_hmac_signature(payload_str)

        url = f"{self.API_BASE_URL}/api/license/activate"
        payload = {
            "key": clean_key,
            "machine_id": self._machine_id,
            "app_version": "1.0.0",
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature,
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()

            if resp.status_code == 200 and data.get("success"):
                lic_data = data.get("data", {})
                server_sig = lic_data.get("signature", "")
                server_ts = lic_data.get("timestamp", 0)

                # Verify server response HMAC signature to prevent MitM proxy response spoofing
                if not verify_server_response_signature(clean_key, lic_data.get("status", "active"), server_ts, server_sig):
                    print("[Security] Rejected activation: Server response signature verification failed!")
                    return LicenseInfo(
                        status=LicenseStatus.SECURITY_VIOLATION,
                        raw_data={"error": {"message": "Server response signature verification failed. Possible proxy interception."}}
                    )

                expires_at = None
                if lic_data.get("expires_at"):
                    expires_at = datetime.fromisoformat(lic_data["expires_at"].replace("Z", "+00:00"))

                self._save_cache(clean_key, lic_data)

                return LicenseInfo(
                    status=LicenseStatus.VALID,
                    key=clean_key,
                    machine_id=self._machine_id,
                    expires_at=expires_at,
                    last_verified=datetime.now(),
                    raw_data=lic_data
                )
            
            # Error handling from response
            err_code = data.get("error", {}).get("code", "")
            if err_code == "LICENSE_REVOKED":
                self._clear_cache()
                return LicenseInfo(status=LicenseStatus.REVOKED)
            elif err_code == "LICENSE_EXPIRED":
                return LicenseInfo(status=LicenseStatus.EXPIRED)
            elif err_code == "ALREADY_ACTIVATED":
                return LicenseInfo(status=LicenseStatus.INVALID, raw_data=data)
            else:
                return LicenseInfo(status=LicenseStatus.INVALID, raw_data=data)

        except requests.RequestException as e:
            print(f"[LicenseManager] Activation network error: {e}")
            return LicenseInfo(status=LicenseStatus.SERVER_ERROR)

    def check_license(self, force_refresh: bool = False) -> LicenseInfo:
        """
        Check active license status. Verifies with server or falls back to offline Grace Period with clock check.
        """
        sec_violation = self._run_security_audit()
        if sec_violation:
            return sec_violation

        cached = self._load_cache()
        if not cached:
            return LicenseInfo(status=LicenseStatus.NOT_FOUND)

        cached_key = cached.get("key", "")
        cached_data = cached.get("data", {})
        saved_at_str = cached.get("saved_at", "")

        # Check system clock rollback tampering
        if detect_clock_tampering(saved_at_str):
            print("[Security] Tampering detected: System clock was turned back!")
            self._clear_cache()
            return LicenseInfo(
                status=LicenseStatus.SECURITY_VIOLATION,
                key=cached_key,
                raw_data={"error": {"message": "System clock rollback detected."}}
            )

        # Parse expiration date
        expires_at = None
        if cached_data.get("expires_at"):
            try:
                expires_at = datetime.fromisoformat(cached_data["expires_at"].replace("Z", "+00:00"))
            except Exception:
                pass

        # Check local expiration
        if expires_at and datetime.now(expires_at.tzinfo) > expires_at:
            return LicenseInfo(status=LicenseStatus.EXPIRED, key=cached_key, machine_id=self._machine_id)

        # Try server verification with HMAC payload signature
        timestamp = int(time.time() * 1000)
        nonce = generate_nonce()
        payload_str = f"{cached_key}|{self._machine_id}|{nonce}|{timestamp}"
        signature = compute_hmac_signature(payload_str)

        url = f"{self.API_BASE_URL}/api/license/verify"
        payload = {
            "key": cached_key,
            "machine_id": self._machine_id,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature,
        }

        try:
            resp = requests.post(url, json=payload, timeout=8)
            data = resp.json()

            if resp.status_code == 200 and data.get("success"):
                lic_data = data.get("data", {})
                server_sig = lic_data.get("signature", "")
                server_ts = lic_data.get("timestamp", 0)

                # Verify server HMAC signature
                if not verify_server_response_signature(cached_key, lic_data.get("valid", True), server_ts, server_sig):
                    print("[Security] Rejected verification: Server response signature mismatch!")
                    return LicenseInfo(
                        status=LicenseStatus.SECURITY_VIOLATION,
                        key=cached_key,
                        raw_data={"error": {"message": "Server response signature verification failed."}}
                    )

                self._save_cache(cached_key, lic_data)

                return LicenseInfo(
                    status=LicenseStatus.VALID,
                    key=cached_key,
                    machine_id=self._machine_id,
                    expires_at=expires_at,
                    last_verified=datetime.now(),
                    raw_data=lic_data
                )
            
            err_code = data.get("error", {}).get("code", "")
            if err_code == "LICENSE_REVOKED":
                self._clear_cache()
                return LicenseInfo(status=LicenseStatus.REVOKED, key=cached_key)
            elif err_code == "LICENSE_EXPIRED":
                return LicenseInfo(status=LicenseStatus.EXPIRED, key=cached_key)
            elif err_code in ["MACHINE_MISMATCH", "INVALID_KEY"]:
                self._clear_cache()
                return LicenseInfo(status=LicenseStatus.INVALID, key=cached_key)

        except requests.RequestException:
            # Network failed — check offline Grace Period
            if saved_at_str:
                try:
                    saved_at = datetime.fromisoformat(saved_at_str)
                    if datetime.now() - saved_at <= timedelta(days=self.GRACE_PERIOD_DAYS):
                        return LicenseInfo(
                            status=LicenseStatus.VALID,
                            key=cached_key,
                            machine_id=self._machine_id,
                            expires_at=expires_at,
                            last_verified=saved_at,
                            raw_data=cached_data
                        )
                except Exception:
                    pass

        return LicenseInfo(status=LicenseStatus.SERVER_ERROR, key=cached_key)

    def deactivate(self) -> bool:
        """
        Deactivate license on the server and remove local cache.
        """
        cached = self._load_cache()
        if not cached:
            self._clear_cache()
            return True

        cached_key = cached.get("key", "")
        url = f"{self.API_BASE_URL}/api/license/deactivate"
        payload = {
            "key": cached_key,
            "machine_id": self._machine_id,
        }

        try:
            resp = requests.post(url, json=payload, timeout=8)
            self._clear_cache()
            return resp.status_code == 200
        except requests.RequestException:
            self._clear_cache()
            return True
