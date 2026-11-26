"""
Data models for subtitle editing.

SubtitleEntry       — a single subtitle cue (index, start, end, text).
SubtitleDocument    — a collection of entries from one SRT file (pure data model).
SubtitleStyle       — base subtitle styling fields shared with RenderConfig.
SubtitleStylePreset — a named style configuration saved as JSON.
"""

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class SubtitleEntry:
    """A single subtitle entry from an SRT file."""
    index: int
    start_time: str  # "HH:MM:SS,mmm"
    end_time: str    # "HH:MM:SS,mmm"
    text: str

    def start_ms(self) -> int:
        return _srt_to_ms(self.start_time)

    def end_ms(self) -> int:
        return _srt_to_ms(self.end_time)

    def duration_ms(self) -> int:
        return self.end_ms() - self.start_ms()

    def set_start_ms(self, ms: int):
        self.start_time = ms_to_srt(ms)

    def set_end_ms(self, ms: int):
        self.end_time = ms_to_srt(ms)

    def shift_ms(self, delta_ms: int):
        """Shift both start and end by delta_ms milliseconds."""
        self.set_start_ms(max(0, self.start_ms() + delta_ms))
        self.set_end_ms(max(0, self.end_ms() + delta_ms))


@dataclass
class SubtitleDocument:
    """All subtitle entries from a single SRT file (I/O lives in SrtService)."""
    file_path: str
    entries: list[SubtitleEntry] = field(default_factory=list)
    dirty: bool = False

    @property
    def name(self) -> str:
        return Path(self.file_path).stem


@dataclass
class SubtitleStyle:
    """Base subtitle styling parameters shared by RenderConfig and SubtitleStylePreset."""

    font_name: str = "Arial"
    font_size: int = 40

    # ---- Fill ----
    font_color: str = "#FFFFFF"      # hex RGB

    # ---- Stroke / Outline ----
    stroke_color: str = "#000000"    # hex RGB
    stroke_width: float = 2.0        # pixels
    stroke_enabled: bool = True

    # ---- Background box ----
    bg_color: str = "#000000"        # hex RGB
    bg_opacity: float = 0.6          # 0.0 – 1.0
    bg_padding_x: int = 8            # horizontal inner padding
    bg_padding_y: int = 4            # vertical inner padding
    bg_corner_radius: int = 4        # pixels (rounded corners)
    bg_enabled: bool = True

    # ---- Shadow ----
    shadow_color: str = "#000000"    # hex RGB
    shadow_opacity: float = 0.8
    shadow_angle: float = 45.0       # degrees (clockwise from top)
    shadow_distance: float = 3.0     # pixels
    shadow_blur: float = 2.0         # pixels
    shadow_enabled: bool = False

    # ---- Layout ----
    alignment: int = 2               # SSA alignment code (2 = bottom-center)
    margin_v: int = 50
    margin_l: int = 20
    margin_r: int = 20

    @staticmethod
    def from_preset(preset: "SubtitleStyle") -> "SubtitleStyle":
        """Create a RenderConfig-compatible SubtitleStyle from a SubtitleStylePreset."""
        return SubtitleStyle(**{f.name: getattr(preset, f.name) for f in fields(SubtitleStyle)})


@dataclass
class SubtitleStylePreset(SubtitleStyle):
    """A named, reusable subtitle style configuration."""

    name: str = "Classic"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SubtitleStylePreset":
        defaults = cls(name="Unnamed")
        kwargs = {f.name: data.get(f.name, getattr(defaults, f.name)) for f in fields(cls)}
        return cls(**kwargs)

    def to_ass_color(self, hex_color: str, alpha: float = 1.0) -> str:
        """Convert hex RGB + opacity to ASS color string &HAABBGGRR."""
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        a = int((1.0 - alpha) * 255)
        return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def _srt_to_ms(timestamp: str) -> int:
    """Convert SRT timestamp 'HH:MM:SS,mmm' to milliseconds."""
    parts = timestamp.replace(",", ":").split(":")
    h, m, s, ms = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return (h * 3600 + m * 60 + s) * 1000 + ms


def ms_to_srt(ms: int) -> str:
    """Convert milliseconds to SRT timestamp 'HH:MM:SS,mmm'."""
    ms = max(0, ms)
    total_s = ms // 1000
    ms = ms % 1000
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


_ms_to_srt = ms_to_srt
