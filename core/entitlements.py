
from dataclasses import dataclass
from typing import Any, Dict

# Fallback used when there is no valid token (e.g. a patched client).
_FREE_FEATURES: Dict[str, Any] = {
    "gpu": False,
    "watermark": True,
    "max_videos": 5,
    "max_layers": 2,
    "priority_support": False,
    "custom_branding": False,
}


@dataclass
class Entitlements:
    gpu: bool = False
    watermark: bool = True
    max_videos: int = 5
    max_layers: int = 2
    custom_branding: bool = False

    @classmethod
    def from_license(cls, info) -> "Entitlements":
        feats = {}
        if info is not None and getattr(info, "is_valid", False):
            feats = getattr(info, "features", None) or {}
        merged = {**_FREE_FEATURES, **feats}
        return cls(
            gpu=bool(merged.get("gpu", False)),
            watermark=bool(merged.get("watermark", True)),
            max_videos=int(merged.get("max_videos", 5)),
            max_layers=int(merged.get("max_layers", 2)),
            custom_branding=bool(merged.get("custom_branding", False)),
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

    # Layer count gating ----------------------------------------------------
    layers = getattr(config, "layers", None)
    if layers and ent.max_layers >= 0:
        enabled_seen = 0
        for layer in layers:
            if getattr(layer, "enabled", False):
                enabled_seen += 1
                if enabled_seen > ent.max_layers:
                    layer.enabled = False

    # Watermark flag (consumed by the render pipeline) --------------------
    try:
        config.watermark_enabled = ent.watermark
    except Exception:
        pass

    return ent
