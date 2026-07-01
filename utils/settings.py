"""Persist user settings to a JSON file next to the script."""

import json
import os
from pathlib import Path

import sys

if getattr(sys, 'frozen', False):
    SETTINGS_PATH = Path(sys.executable).parent / "settings.json"
else:
    SETTINGS_PATH = Path(__file__).parent.parent / "settings.json"

DEFAULTS = {
    "bg_folder": "",
    "audio_folder": "",
    "srt_folder": "",
    "output_folder": "",
    "font_name": "Arial",
    "font_size": 40,
    "slow_min": 35.0,
    "slow_max": 45.0,
    "codec": "hevc_nvenc",
    "use_gpu": True,
    "subtitle_alignment": 2,
    "logo_enabled_1": False,
    "logo_path_1": "",
    "logo_position_1": 2,
    "logo_size_1": 100,
    "logo_opacity_1": 90,
    "logo_margin_t_1": 20,
    "logo_margin_b_1": 20,
    "logo_margin_l_1": 20,
    "logo_margin_r_1": 20,

    "logo_enabled_2": False,
    "logo_path_2": "",
    "logo_position_2": 0,
    "logo_size_2": 100,
    "logo_opacity_2": 90,
    "logo_margin_t_2": 20,
    "logo_margin_b_2": 20,
    "logo_margin_l_2": 20,
    "logo_margin_r_2": 20,

    "logo_enabled_3": False,
    "logo_path_3": "",
    "logo_position_3": 1,
    "logo_size_3": 100,
    "logo_opacity_3": 90,
    "logo_margin_t_3": 20,
    "logo_margin_b_3": 20,
    "logo_margin_l_3": 20,
    "logo_margin_r_3": 20,

    "logo_enabled_4": False,
    "logo_path_4": "",
    "logo_position_4": 3,
    "logo_size_4": 100,
    "logo_opacity_4": 90,
    "logo_margin_t_4": 20,
    "logo_margin_b_4": 20,
    "logo_margin_l_4": 20,
    "logo_margin_r_4": 20,

    "logo_enabled_5": False,
    "logo_path_5": "",
    "logo_position_5": 4,
    "logo_size_5": 100,
    "logo_opacity_5": 90,
    "logo_margin_t_5": 20,
    "logo_margin_b_5": 20,
    "logo_margin_l_5": 20,
    "logo_margin_r_5": 20,
}


def load() -> dict:
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults so new keys always exist
            merged = {**DEFAULTS, **data}
            return merged
        except Exception:
            pass
    return dict(DEFAULTS)


def save(settings: dict):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Settings] Cannot save: {e}")