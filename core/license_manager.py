import os
import sys
import json
import time
import uuid
import hashlib
import platform
import requests
from enum import Enum
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from core.security import (
    is_debugger_present,
    scan_suspicious_processes,
    get_windows_machine_guid,
    compute_hmac_signature,
    compute_cache_hmac,
    verify_license_token,
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


def _dt_from_ms(ms: Optional[int]) -> Optional[datetime]:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except Exception:
        return None


@dataclass
class LicenseInfo:
    status: LicenseStatus
    key: str = ""
    machine_id: str = ""
    plan: str = ""
    features: Dict[str, Any] = field(default_factory=dict)
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    max_devices: int = 1
    last_verified: Optional[datetime] = None
    token_expires_at: Optional[datetime] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.status == LicenseStatus.VALID


class LicenseManager:
    DEFAULT_API_URL = "https://encomie-server.19novemberrr.workers.dev"

    def __init__(self, api_url: Optional[str] = None):
        raw_url = api_url or os.environ.get("LICENSE_API_URL", self.DEFAULT_API_URL)
        self.API_BASE_URL = raw_url.rstrip("/")
        self._machine_id = self.get_machine_id()
        self._cache_file = self._get_cache_filepath()

    # ------------------------------------------------------------------ #
    # Hardware identity
    # ------------------------------------------------------------------ #

    @staticmethod
    def _hw_components() -> Dict[str, str]:
        return {
            "machine_guid": get_windows_machine_guid(),
            "node": platform.node(),
            "arch": platform.machine(),
            "cpu": platform.processor(),
            "mac": str(uuid.getnode()),
        }

    @classmethod
    def get_machine_id(cls) -> str:
        """Stable 32-char HWID derived from hardware attributes + Registry GUID."""
        try:
            comps = cls._hw_components()
            raw_id = "|".join(comps[k] for k in ("machine_guid", "node", "arch", "cpu", "mac"))
            return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:32]
        except Exception:
            return hashlib.sha256(b"encomie_fallback_hwid").hexdigest()[:32]

    # ------------------------------------------------------------------ #
    # Local cache
    # ------------------------------------------------------------------ #

    def _get_cache_filepath(self) -> Path:
        if sys.platform.startswith("win"):
            base_dir = Path(os.environ.get("APPDATA", Path.home())) / "EncoMie"
        else:
            base_dir = Path.home() / ".config" / "encomie"
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir / "license.json"

    def _save_cache(self, key: str, token: str):
        try:
            saved_at = datetime.now().isoformat()
            checksum = compute_cache_hmac(key, self._machine_id, saved_at, token)
            payload = {"key": key, "machine_id": self._machine_id, "token": token,
                       "saved_at": saved_at, "checksum": checksum}
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            print(f"[LicenseManager] Warning: failed to save cache: {e}")

    def _load_cache(self) -> Optional[Dict[str, Any]]:
        if not self._cache_file.exists():
            return None
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            key = payload.get("key", "")
            token = payload.get("token", "")
            saved_at = payload.get("saved_at", "")
            expected = compute_cache_hmac(key, payload.get("machine_id", ""), saved_at, token)
            if not payload.get("checksum") or expected != payload.get("checksum"):
                print("[Security] Local license cache checksum mismatch - file was edited.")
                self._clear_cache()
                return None
            return payload
        except Exception as e:
            print(f"[LicenseManager] Cache unreadable ({e}); clearing.")
            self._clear_cache()
            return None

    def _clear_cache(self):
        try:
            if self._cache_file.exists():
                self._cache_file.unlink()
        except Exception as e:
            print(f"[LicenseManager] Failed to clear cache: {e}")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _run_security_audit(self) -> Optional[LicenseInfo]:
        if is_debugger_present():
            return LicenseInfo(status=LicenseStatus.SECURITY_VIOLATION,
                               raw_data={"error": {"message": "Debugger detected. App execution restricted."}})
        proc = scan_suspicious_processes()
        if proc:
            return LicenseInfo(status=LicenseStatus.SECURITY_VIOLATION,
                               raw_data={"error": {"message": f"Suspicious process '{proc}' detected."}})
        return None

    def _signed_body(self, key: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        nonce = generate_nonce()
        timestamp = int(time.time() * 1000)
        signature = compute_hmac_signature(f"{key}|{self._machine_id}|{nonce}|{timestamp}")
        body = {"key": key, "machine_id": self._machine_id, "nonce": nonce,
                "timestamp": timestamp, "signature": signature,
                "hw_components": self._hw_components()}
        if extra:
            body.update(extra)
        return body

    def _info_from_token(self, key: str, claims: Dict[str, Any], *, offline: bool = False) -> LicenseInfo:
        return LicenseInfo(
            status=LicenseStatus.VALID,
            key=key,
            machine_id=claims.get("machine_id", self._machine_id),
            plan=claims.get("plan", ""),
            features=claims.get("features", {}) or {},
            expires_at=_dt_from_ms(claims.get("license_expires_at")),
            created_at=_dt_from_ms(claims.get("created_at")),
            max_devices=claims.get("max_devices", 1) or 1,
            last_verified=None if offline else datetime.now(),
            token_expires_at=_dt_from_ms(claims.get("exp")),
            raw_data=claims,
        )

    def _validate_claims(self, key: str, claims: Dict[str, Any]) -> Optional[LicenseInfo]:
        """Return a non-VALID LicenseInfo if the token claims fail a local check, else None."""
        if claims.get("machine_id") != self._machine_id:
            return LicenseInfo(status=LicenseStatus.INVALID, key=key,
                               raw_data={"error": {"message": "License token is bound to another machine."}})
        status = str(claims.get("status", "")).lower()
        if status == "revoked":
            return LicenseInfo(status=LicenseStatus.REVOKED, key=key)
        now_ms = int(time.time() * 1000)
        lic_exp = claims.get("license_expires_at")
        if lic_exp and now_ms > lic_exp:
            return LicenseInfo(status=LicenseStatus.EXPIRED, key=key,
                               expires_at=_dt_from_ms(lic_exp))
        return None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def activate(self, key: str) -> LicenseInfo:
        sec = self._run_security_audit()
        if sec:
            return sec

        clean_key = key.strip().upper()
        if not clean_key:
            return LicenseInfo(status=LicenseStatus.INVALID)

        try:
            resp = requests.post(f"{self.API_BASE_URL}/api/license/activate",
                                 json=self._signed_body(clean_key, {"app_version": "1.0.0"}), timeout=10)
            data = resp.json()
        except requests.RequestException as e:
            print(f"[LicenseManager] Activation network error: {e}")
            return LicenseInfo(status=LicenseStatus.SERVER_ERROR)

        if resp.status_code == 200 and data.get("success"):
            token = data.get("data", {}).get("token", "")
            claims = verify_license_token(token)
            if not claims:
                return LicenseInfo(status=LicenseStatus.SECURITY_VIOLATION,
                                   raw_data={"error": {"message": "Server response signature invalid. Possible proxy interception."}})
            bad = self._validate_claims(clean_key, claims)
            if bad:
                return bad
            self._save_cache(clean_key, token)
            return self._info_from_token(clean_key, claims)

        err_code = data.get("error", {}).get("code", "")
        if err_code == "LICENSE_REVOKED":
            self._clear_cache()
            return LicenseInfo(status=LicenseStatus.REVOKED, raw_data=data)
        if err_code == "LICENSE_EXPIRED":
            return LicenseInfo(status=LicenseStatus.EXPIRED, raw_data=data)
        return LicenseInfo(status=LicenseStatus.INVALID, raw_data=data)

    def check_license(self, force_refresh: bool = False) -> LicenseInfo:
        sec = self._run_security_audit()
        if sec:
            return sec

        cached = self._load_cache()
        if not cached:
            return LicenseInfo(status=LicenseStatus.NOT_FOUND)

        cached_key = cached.get("key", "")
        claims = verify_license_token(cached.get("token", ""))
        if not claims:
            print("[Security] Cached license token failed signature verification; clearing.")
            self._clear_cache()
            return LicenseInfo(status=LicenseStatus.NOT_FOUND)

        bad = self._validate_claims(cached_key, claims)
        if bad:
            if bad.status in (LicenseStatus.REVOKED, LicenseStatus.INVALID):
                self._clear_cache()
            return bad

        # ---- Try online verification (refreshes the token / TTL) ----
        try:
            resp = requests.post(f"{self.API_BASE_URL}/api/license/verify",
                                 json=self._signed_body(cached_key), timeout=8)
            data = resp.json()

            if resp.status_code == 200 and data.get("success"):
                token = data.get("data", {}).get("token", "")
                new_claims = verify_license_token(token)
                if not new_claims:
                    return LicenseInfo(status=LicenseStatus.SECURITY_VIOLATION, key=cached_key,
                                       raw_data={"error": {"message": "Server response signature invalid."}})
                nbad = self._validate_claims(cached_key, new_claims)
                if nbad:
                    if nbad.status in (LicenseStatus.REVOKED, LicenseStatus.INVALID):
                        self._clear_cache()
                    return nbad
                self._save_cache(cached_key, token)
                return self._info_from_token(cached_key, new_claims)

            err_code = data.get("error", {}).get("code", "")
            if err_code == "LICENSE_REVOKED":
                self._clear_cache()
                return LicenseInfo(status=LicenseStatus.REVOKED, key=cached_key)
            if err_code == "LICENSE_EXPIRED":
                return LicenseInfo(status=LicenseStatus.EXPIRED, key=cached_key,
                                   expires_at=_dt_from_ms(claims.get("license_expires_at")))
            if err_code in ("MACHINE_MISMATCH", "INVALID_KEY", "NOT_ACTIVATED"):
                self._clear_cache()
                return LicenseInfo(status=LicenseStatus.INVALID, key=cached_key)
            # Unknown server error -> fall through to offline check.

        except requests.RequestException:
            pass  # offline path below

        # ---- Offline: the signed token's exp is the only clock ----
        now_ms = int(time.time() * 1000)
        if claims.get("exp", 0) > now_ms:
            return self._info_from_token(cached_key, claims, offline=True)

        return LicenseInfo(
            status=LicenseStatus.EXPIRED, key=cached_key,
            token_expires_at=_dt_from_ms(claims.get("exp")),
            raw_data={"error": {"message": "Bản quyền cần kết nối internet để xác thực lại."}},
        )

    def deactivate(self) -> bool:
        cached = self._load_cache()
        if not cached:
            self._clear_cache()
            return True
        cached_key = cached.get("key", "")
        try:
            resp = requests.post(f"{self.API_BASE_URL}/api/license/deactivate",
                                 json=self._signed_body(cached_key), timeout=8)
            self._clear_cache()
            return resp.status_code == 200
        except requests.RequestException:
            self._clear_cache()
            return True
