"""
Quality settings model with TOML persistence and built-in presets.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

QUALITY_FILENAME = "quality.toml"


# ── Data Models ──────────────────────────────────────────────────────────────


class QualitySettings(BaseModel):
    """Concrete transcode parameters."""

    crf: int = Field(default=18, ge=0, le=51)
    preset: str = Field(default="slow")
    audio_bitrate: str = Field(default="256k")
    resolution_cap: int | None = Field(default=None)


class QualityPreset(StrEnum):
    LOW = "low"
    MID = "mid"
    HIGH = "high"


PRESETS: dict[QualityPreset, QualitySettings] = {
    QualityPreset.LOW: QualitySettings(
        crf=28, preset="faster", audio_bitrate="128k", resolution_cap=720
    ),
    QualityPreset.MID: QualitySettings(
        crf=23, preset="medium", audio_bitrate="192k", resolution_cap=1080
    ),
    QualityPreset.HIGH: QualitySettings(
        crf=18, preset="slow", audio_bitrate="256k", resolution_cap=None
    ),
}


class QualityState(BaseModel):
    """Persisted quality configuration."""

    active_preset: QualityPreset | None = QualityPreset.HIGH
    settings: QualitySettings = Field(default_factory=lambda: PRESETS[QualityPreset.HIGH].model_copy())


# ── TOML Persistence ────────────────────────────────────────────────────────

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

import tomli_w


def _quality_path(directory: Path) -> Path:
    return directory / QUALITY_FILENAME


def load_quality(directory: Path) -> QualityState:
    """Load quality state from TOML. Returns high-preset defaults if missing."""
    path = _quality_path(directory)
    if not path.exists():
        return QualityState()

    with open(path, "rb") as f:
        data = tomllib.load(f)

    # Reconstruct from flat TOML structure
    settings_data = data.get("settings", {})
    active_preset = data.get("active_preset")
    if active_preset == "custom":
        active_preset = None

    return QualityState(
        active_preset=active_preset,
        settings=QualitySettings(**settings_data),
    )


def save_quality(directory: Path, state: QualityState) -> None:
    """Persist quality state to TOML."""
    directory.mkdir(parents=True, exist_ok=True)
    path = _quality_path(directory)

    data: dict = {
        "active_preset": state.active_preset.value if state.active_preset else "custom",
        "settings": state.settings.model_dump(exclude_none=True),
    }

    with open(path, "wb") as f:
        tomli_w.dump(data, f)
