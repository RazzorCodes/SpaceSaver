"""Tests for classifier.py — clean_filename and classify."""

from classifier import classify, clean_filename
from models import DeclaredMetadata, UNKNOWN_SENTINEL


# ── clean_filename tests ────────────────────────────────────────────────────

def test_clean_filename_movie():
    assert clean_filename("Inception.2010.1080p.Bluray.mkv") == "Inception"


def test_clean_filename_tv():
    # clean_filename retains the episode string if there's no year
    assert clean_filename("Breaking.Bad.S01E01.720p.mkv") == "Breaking Bad S01E01"


def test_clean_filename_with_watermark():
    result = clean_filename("www.UIndex.org - Harry.Potter.2001.mkv")
    assert "Harry Potter" in result


def test_clean_filename_underscores():
    assert clean_filename("The_Dark_Knight.2008.x264.mkv") == "The Dark Knight"


def test_clean_filename_no_year():
    result = clean_filename("some.random.hevc.mkv")
    # Should strip junk tokens
    assert "hevc" not in result.lower()


def test_clean_filename_very_long_title():
    long_name = "A" * 200 + ".2020.mkv"
    result = clean_filename(long_name)
    assert len(result) <= 120


def test_clean_filename_empty_result_fallback():
    # Edge case: filename is all junk tokens
    result = clean_filename("1080p.x265.hevc.mkv")
    # Should return something (fallback to raw)
    assert len(result) > 0


# ── classify tests ──────────────────────────────────────────────────────────

def test_classify_returns_declared_metadata():
    result = classify("Inception.2010.1080p.x264.mkv")
    assert isinstance(result, DeclaredMetadata)


def test_classify_extracts_codec():
    result = classify("Movie.2020.x265.mkv")
    assert result.codec == "h265"


def test_classify_extracts_resolution():
    result = classify("Movie.2020.1080p.mkv")
    assert result.resolution == "1920x1080"


def test_classify_extracts_4k():
    result = classify("Movie.2020.2160p.mkv")
    assert result.resolution == "3840x2160"


def test_classify_extracts_hdr_format():
    result = classify("Movie.2020.HDR10.mkv")
    assert result.format != UNKNOWN_SENTINEL
    assert "hdr" in result.format.lower()


def test_classify_unknown_fields():
    result = classify("simple_movie.mkv")
    # No codec, no resolution in filename → Unknown
    assert result.codec == UNKNOWN_SENTINEL
    assert result.resolution == UNKNOWN_SENTINEL


def test_classify_no_exceptions():
    """Classify should never raise, even on pathological input."""
    for edge_case in ["", "   ", "...", "🎬🎥.mkv", "\x00\x01\x02"]:
        result = classify(edge_case)
        assert isinstance(result, DeclaredMetadata)


def test_classify_partial_failure():
    """If one field fails, others should still parse."""
    result = classify("Movie.2020.x264.10bit.1080p.mkv")
    assert result.codec == "h264"
    assert result.resolution == "1920x1080"
    # format should pick up 10bit
    assert result.format != UNKNOWN_SENTINEL


def test_classify_sar_dar_unknown():
    """SAR and DAR are rarely in filenames — should default to Unknown."""
    result = classify("Movie.2020.1080p.x265.mkv")
    assert result.sar == UNKNOWN_SENTINEL
    assert result.dar == UNKNOWN_SENTINEL


def test_classify_framerate():
    result = classify("Movie.2020.23.98fps.1080p.mkv")
    assert result.framerate == "23.98"
