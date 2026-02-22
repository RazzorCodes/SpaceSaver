"""Tests for classifier.py — table-driven, covering separators and edge cases."""

import pytest
from classifier import classify, clean_filename
from models import UNKNOWN_SENTINEL


# ── classify: table-driven ──────────────────────────────────────────────────

_CLASSIFY_CASES = [
    # (filename, expected_codec, expected_resolution, expected_format)
    # Dot separators
    ("Inception.2010.1080p.x264.mkv",          "h264",  "1920x1080", UNKNOWN_SENTINEL),
    ("Movie.2020.x265.mkv",                    "h265",  UNKNOWN_SENTINEL, UNKNOWN_SENTINEL),
    ("Movie.2020.2160p.mkv",                   UNKNOWN_SENTINEL, "3840x2160", UNKNOWN_SENTINEL),
    ("Movie.2020.HDR10.mkv",                   UNKNOWN_SENTINEL, UNKNOWN_SENTINEL, "hdr10"),
    ("Movie.2020.x264.10bit.1080p.mkv",        "h264",  "1920x1080", "10bit"),
    ("Movie.2020.23.98fps.1080p.mkv",          UNKNOWN_SENTINEL, "1920x1080", UNKNOWN_SENTINEL),
    # Underscore separators
    ("test_video_h264.mkv",                    "h264",  UNKNOWN_SENTINEL, UNKNOWN_SENTINEL),
    ("my_movie_x265_1080p.mkv",                "h265",  "1920x1080", UNKNOWN_SENTINEL),
    ("file_hevc_4k.mkv",                       "hevc",  "3840x2160", UNKNOWN_SENTINEL),
    # Dash separators
    ("movie-h264-720p.mkv",                    "h264",  "1280x720",  UNKNOWN_SENTINEL),
    ("clip-xvid-480p.mkv",                     "xvid",  "720x480",   UNKNOWN_SENTINEL),
    # Bracket garbage
    ("[GARBAGE]h264.1080p.mkv",                "h264",  "1920x1080", UNKNOWN_SENTINEL),
    ("[YTS.MX]Movie.2020.x265.mkv",            "h265",  UNKNOWN_SENTINEL, UNKNOWN_SENTINEL),
    ("(Release-Group)_movie_av1_2160p.mkv",    "av1",   "3840x2160", UNKNOWN_SENTINEL),
    # Mixed separators
    ("Some.Movie_2020-x264.1080p.mkv",         "h264",  "1920x1080", UNKNOWN_SENTINEL),
    # No codec / no resolution → Unknown
    ("simple_movie.mkv",                       UNKNOWN_SENTINEL, UNKNOWN_SENTINEL, UNKNOWN_SENTINEL),
    # Edge cases — should never crash
    ("",                                       UNKNOWN_SENTINEL, UNKNOWN_SENTINEL, UNKNOWN_SENTINEL),
    ("   ",                                    UNKNOWN_SENTINEL, UNKNOWN_SENTINEL, UNKNOWN_SENTINEL),
    ("...",                                    UNKNOWN_SENTINEL, UNKNOWN_SENTINEL, UNKNOWN_SENTINEL),
    ("🎬🎥.mkv",                                UNKNOWN_SENTINEL, UNKNOWN_SENTINEL, UNKNOWN_SENTINEL),
]

@pytest.mark.parametrize("filename,exp_codec,exp_res,exp_fmt", _CLASSIFY_CASES)
def test_classify(filename, exp_codec, exp_res, exp_fmt):
    result = classify(filename)
    assert result.codec == exp_codec, f"{filename}: codec {result.codec!r} != {exp_codec!r}"
    assert result.resolution == exp_res, f"{filename}: resolution {result.resolution!r} != {exp_res!r}"
    assert result.format == exp_fmt, f"{filename}: format {result.format!r} != {exp_fmt!r}"


# ── clean_filename: table-driven ────────────────────────────────────────────

_CLEAN_CASES = [
    ("Inception.2010.1080p.Bluray.mkv",                   "Inception"),
    ("The_Dark_Knight.2008.x264.mkv",                     "The Dark Knight"),
    ("www.UIndex.org - Harry.Potter.2001.mkv",             "Harry Potter"),
    ("Breaking.Bad.S01E01.720p.mkv",                       "Breaking Bad S01E01"),
    ("some.random.hevc.mkv",                               None),  # just check no crash + no junk
    ("A" * 200 + ".2020.mkv",                              None),  # check length <= 120
]

@pytest.mark.parametrize("filename,expected", _CLEAN_CASES)
def test_clean_filename(filename, expected):
    result = clean_filename(filename)
    assert len(result) > 0, f"Empty result for {filename!r}"
    if expected is not None:
        assert expected in result, f"{filename!r} → {result!r} does not contain {expected!r}"
    else:
        # Just verify no crash and reasonable length
        assert len(result) <= 120
        if "hevc" in filename.lower():
            assert "hevc" not in result.lower()
