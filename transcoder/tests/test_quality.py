"""Tests for the quality settings model and TOML persistence."""

import pytest
from pathlib import Path

from models.quality import (
    PRESETS,
    QualityPreset,
    QualitySettings,
    QualityState,
    load_quality,
    save_quality,
)


class TestQualitySettings:
    """Validation tests for QualitySettings."""

    def test_defaults_match_high_preset(self):
        s = QualitySettings()
        high = PRESETS[QualityPreset.HIGH]
        assert s.crf == high.crf
        assert s.preset == high.preset
        assert s.audio_bitrate == high.audio_bitrate
        assert s.resolution_cap == high.resolution_cap

    def test_crf_out_of_range_raises(self):
        with pytest.raises(Exception):
            QualitySettings(crf=-1)
        with pytest.raises(Exception):
            QualitySettings(crf=52)

    def test_crf_boundaries_valid(self):
        assert QualitySettings(crf=0).crf == 0
        assert QualitySettings(crf=51).crf == 51


class TestPresets:
    """Verify built-in presets have the expected values."""

    def test_low_preset(self):
        p = PRESETS[QualityPreset.LOW]
        assert p.crf == 28
        assert p.preset == "faster"
        assert p.audio_bitrate == "128k"
        assert p.resolution_cap == 720

    def test_mid_preset(self):
        p = PRESETS[QualityPreset.MID]
        assert p.crf == 23
        assert p.preset == "medium"
        assert p.audio_bitrate == "192k"
        assert p.resolution_cap == 1080

    def test_high_preset(self):
        p = PRESETS[QualityPreset.HIGH]
        assert p.crf == 18
        assert p.preset == "slow"
        assert p.audio_bitrate == "256k"
        assert p.resolution_cap is None


class TestTOMLPersistence:
    """Round-trip save/load tests using a tmp directory."""

    def test_load_missing_file_returns_default(self, tmp_path: Path):
        state = load_quality(tmp_path)
        assert state.active_preset == QualityPreset.HIGH
        assert state.settings.crf == 18

    def test_save_and_load_preset(self, tmp_path: Path):
        state = QualityState(
            active_preset=QualityPreset.LOW,
            settings=PRESETS[QualityPreset.LOW].model_copy(),
        )
        save_quality(tmp_path, state)
        loaded = load_quality(tmp_path)
        assert loaded.active_preset == QualityPreset.LOW
        assert loaded.settings.crf == 28
        assert loaded.settings.resolution_cap == 720

    def test_save_and_load_custom(self, tmp_path: Path):
        custom = QualitySettings(crf=30, preset="veryfast", audio_bitrate="64k", resolution_cap=480)
        state = QualityState(active_preset=None, settings=custom)
        save_quality(tmp_path, state)

        loaded = load_quality(tmp_path)
        assert loaded.active_preset is None
        assert loaded.settings.crf == 30
        assert loaded.settings.preset == "veryfast"
        assert loaded.settings.audio_bitrate == "64k"
        assert loaded.settings.resolution_cap == 480

    def test_file_created_in_directory(self, tmp_path: Path):
        save_quality(tmp_path, QualityState())
        assert (tmp_path / "quality.toml").exists()

    def test_overwrite_preserves_latest(self, tmp_path: Path):
        save_quality(
            tmp_path,
            QualityState(active_preset=QualityPreset.LOW, settings=PRESETS[QualityPreset.LOW].model_copy()),
        )
        save_quality(
            tmp_path,
            QualityState(active_preset=QualityPreset.MID, settings=PRESETS[QualityPreset.MID].model_copy()),
        )
        loaded = load_quality(tmp_path)
        assert loaded.active_preset == QualityPreset.MID
        assert loaded.settings.crf == 23
