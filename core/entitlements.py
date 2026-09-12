"""
Plan entitlements enforcement (Phase 2 / P2).

Two plans: free and pro. No watermark is ever applied to rendered output on
either plan. Feature limits come from the *signed* license token
(``LicenseInfo.features``), not from a single "is licensed" boolean. This means
patching ``is_valid`` to True is not enough to unlock Pro output: with no valid
token the features dict is empty, the app is treated as ``free`` and GPU /
extra layers are withheld, and the daily render quota applies.
"""

from dataclasses import dataclass
from typing import Any, Dict

# Fallback used when there is no valid token (e.g. a patched client).
_FREE_FEATURES: Dict[str, Any] = {
    "gpu": False,
    "max_videos": 50,   # per day
    "max_layers": 2,
    "color_grade": False,
    "priority_support": False,
}


@dataclass
class Entitlements:
    gpu: bool = False
    max_videos: int = 50  # -1 = unlimited; otherwise a per-day quota
    max_layers: int = 2
    color_grade: bool = False

    @classmethod
    def from_license(cls, info) -> "Entitlements":
        feats = {}
        if info is not None and getattr(info, "is_valid", False):
            feats = getattr(info, "features", None) or {}
        merged = {**_FREE_FEATURES, **feats}
        return cls(
            gpu=bool(merged.get("gpu", False)),
            max_videos=int(merged.get("max_videos", 50)),
            max_layers=int(merged.get("max_layers", 2)),
            color_grade=bool(merged.get("color_grade", False)),
        )


def apply_to_render_config(config, info) -> Entitlements:
    """
    Clamp a RenderConfig in place to what the license actually permits and
    return the resolved Entitlements (so the UI / pipeline can act on them).
    """
    ent = Entitlements.from_license(info)

    # GPU / NVENC gating -------------------------------------------------
    if not ent.gpu:
        config.use_gpu = False
        codec = str(getattr(config, "codec", "") or "")
        if "nvenc" in codec:
            # Forced onto CPU by the licence -> use x264 (much faster than CPU
            # HEVC). An explicit libx265 pick is left untouched.
            config.codec = "libx264"

    # Per-layer colour grade gating -------------------------------------
    if not ent.color_grade:
        for layer in (getattr(config, "layers", None) or []):
            cg = getattr(layer, "color_grade", None)
            if cg is not None:
                cg.enabled = False

    # Layer count gating ----------------------------------------------------
    layers = getattr(config, "layers", None)
    if layers and ent.max_layers >= 0:
        enabled_seen = 0
        for layer in layers:
            if getattr(layer, "enabled", False):
                enabled_seen += 1
                if enabled_seen > ent.max_layers:
                    layer.enabled = False

    return ent
