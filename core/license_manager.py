import os
import json
import time
import uuid
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
from core.hardware_id import (
    get_stable_machine_id,
    get_legacy_machine_id,
    get_smbios_uuid,
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

    # Running several EncoMie processes at once on the same machine is a
    # supported workflow (e.g. parallel batches), not something to lock out.
    # But each instance's own periodic heartbeat (main window: every ~12 min;
    # worker: every >=60s while rendering) hits the network independently, so
    # N instances meant N times the /verify traffic for the exact same
    # key+machine. All instances share the same license.json, and a token
    # carries the server's issue time (`iat`), so a non-forced check can just
    # trust a cache another process (or this one) refreshed within this window
    # instead of repeating the round-trip. The trade-off is detection latency:
    # a revocation is noticed up to this long late during active use, which for
    # a desktop tool is fine. force_refresh=True (pre-render, dialog open)
    # always bypasses this.
    HEARTBEAT_COALESCE_MS = 600_000

    def __init__(self, api_url: Optional[str] = None):
        raw_url = api_url or os.environ.get("LICENSE_API_URL", self.DEFAULT_API_URL)
        self.API_BASE_URL = raw_url.rstrip("/")
        self._machine_id = self.get_machine_id()
        self._legacy_machine_id = self.get_legacy_machine_id()
        self._cache_file = self._get_cache_filepath()

    # ------------------------------------------------------------------ #
    # Hardware identity
    # ------------------------------------------------------------------ #

    @staticmethod
    def _hw_components() -> Dict[str, str]:
        comps = {
            "machine_guid": get_windows_machine_guid(),
            "node": platform.node(),
            "arch": platform.machine(),
            "cpu": platform.processor(),
            "mac": str(uuid.getnode()),
            "smbios_uuid": get_smbios_uuid() or "",
            "hwid_v2": get_stable_machine_id(),
        }
        return comps

    @classmethod
    def get_machine_id(cls) -> str:
        """Stable 32-char HWID v2 derived from physical hardware attributes (SMBIOS, board, CPU, disk)."""
        return get_stable_machine_id()

    @classmethod
    def get_legacy_machine_id(cls) -> str:
        """Legacy HWID v1 for backward compatibility with older Windows 10/11 activations."""
        return get_legacy_machine_id()

    # ------------------------------------------------------------------ #
    # Local cache
    # ------------------------------------------------------------------ #

    def _get_cache_filepath(self) -> Path:
        from core.app_paths import app_data_dir
        return app_data_dir() / "license.json"

    def _save_cache(self, key: str, token: str, machine_id: Optional[str] = None):
        mid = machine_id or self._machine_id
        try:
            saved_at = datetime.now().isoformat()
            checksum = compute_cache_hmac(key, mid, saved_at, token)
            payload = {"key": key, "machine_id": mid, "token": token,
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

    def _run_security_audit(self, deep: bool = False) -> Optional[LicenseInfo]:
        """
        Fast anti-tamper check. `deep=True` also runs the ~150ms process scan
        (`tasklist`); the periodic/render-path callers pass deep=False because
        the UI's realtime watchdog already scans processes continuously.
        """
        if is_debugger_present():
            return LicenseInfo(status=LicenseStatus.SECURITY_VIOLATION,
                               raw_data={"error": {"message": "Debugger detected. App execution restricted."}})
        if deep:
            proc = scan_suspicious_processes()
            if proc:
                return LicenseInfo(status=LicenseStatus.SECURITY_VIOLATION,
                                   raw_data={"error": {"message": f"Suspicious process '{proc}' detected."}})
        return None

    def _signed_body(self, key: str, extra: Optional[Dict[str, Any]] = None, machine_id_override: Optional[str] = None) -> Dict[str, Any]:
        mid = machine_id_override or self._machine_id
        nonce = generate_nonce()
        timestamp = int(time.time() * 1000)
        signature = compute_hmac_signature(f"{key}|{mid}|{nonce}|{timestamp}")
        body = {"key": key, "machine_id": mid, "nonce": nonce,
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
        claimed_mid = claims.get("machine_id")
        valid_mids = {self._machine_id, self._legacy_machine_id}
        if claimed_mid not in valid_mids:
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
        sec = self._run_security_audit(deep=True)
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

        # Coalesce: skip the round-trip if the shared cache was refreshed very
        # recently — by this process's own last check, or another instance's.
        if not force_refresh:
            age_ms = int(time.time() * 1000) - int(claims.get("iat", 0))
            if 0 <= age_ms < self.HEARTBEAT_COALESCE_MS:
                return self._info_from_token(cached_key, claims, offline=False)

        # Hỗ trợ máy cũ: nếu token trong máy đã cấp cho legacy machine_id,
        # gửi target_mid tương ứng để server khớp đúng bản ghi đã kích hoạt
        claimed_mid = claims.get("machine_id", self._machine_id)
        target_mid = claimed_mid if claimed_mid in (self._machine_id, self._legacy_machine_id) else self._machine_id

        # ---- Try online verification (refreshes the token / TTL) ----
        try:
            extra_payload = {"hwid_v2": self._machine_id} if target_mid == self._legacy_machine_id else None
            resp = requests.post(
                f"{self.API_BASE_URL}/api/license/verify",
                json=self._signed_body(cached_key, extra=extra_payload, machine_id_override=target_mid),
                timeout=8,
            )
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
                new_token_mid = new_claims.get("machine_id", target_mid)
                self._save_cache(cached_key, token, machine_id=new_token_mid)
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
        cached_mid = cached.get("machine_id", self._machine_id)
        target_mid = cached_mid if cached_mid in (self._machine_id, self._legacy_machine_id) else self._machine_id
        try:
            resp = requests.post(
                f"{self.API_BASE_URL}/api/license/deactivate",
                json=self._signed_body(cached_key, machine_id_override=target_mid),
                timeout=8,
            )
            self._clear_cache()
            return resp.status_code == 200
        except requests.RequestException:
            self._clear_cache()
            return True
