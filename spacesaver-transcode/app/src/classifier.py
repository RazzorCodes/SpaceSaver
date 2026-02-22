"""
classifier.py — Determine media metadata from a filename string.

Hardened per §2.2:
  - Input:  raw filename string
  - Output: DeclaredMetadata dataclass — never a dict, never None
  - All parsing is defensive: a field parse failure does not affect other fields
  - No exceptions escape — partial results with Unknown sentinels
  - Fully unit-testable without filesystem access or ffprobe
"""

from __future__ import annotations

import logging
import os
import re

from models import DeclaredMetadata, UNKNOWN_SENTINEL

log = logging.getLogger(__name__)

# ── Patterns ─────────────────────────────────────────────────────────────────

# Episode detection: e.g. S01E03, s02e14, Season 2, /Season 02/
_EP_PATTERN = re.compile(
    r"[Ss]\d{1,2}[Ee]\d{1,2}"
    r"|[Ss]eason\s*\d{1,2}"
    r"|/[Ss]eason[\s._-]*\d{1,2}/",
    re.IGNORECASE,
)

_EP_LABEL_RE = re.compile(r"([Ss]\d{1,2}[Ee]\d{1,2})", re.IGNORECASE)
_SEASON_LABEL_RE = re.compile(r"[Ss]eason[\s._-]*(\d{1,2})", re.IGNORECASE)

# Year: 4-digit number in the 1900s or 2000s
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# Resolution patterns
_RESOLUTION_RE = re.compile(
    r"\b(2160p|1080p|1080i|720p|576p|480p|4[Kk]|[Uu][Hh][Dd])\b",
    re.IGNORECASE,
)

# Codec patterns from filename
_CODEC_RE = re.compile(
    r"\b(hevc|x265|x264|h\.?264|h\.?265|avc|xvid|divx|av1|vp9|vp8)\b",
    re.IGNORECASE,
)

# Format / pixel format indicators
_FORMAT_RE = re.compile(
    r"\b(10[._-]?bit|10bit|8bit|12bit|hdr|hdr10|hdr10\+|dv|dolby[\._\s]?vision|hlg)\b",
    re.IGNORECASE,
)

# SAR/DAR patterns (unlikely in filenames but defensive)
_DAR_RE = re.compile(r"\b(\d+:\d+)\b")

# Framerate patterns
_FRAMERATE_RE = re.compile(
    r"\b(\d{2}(?:\.\d{1,2})?)\s*fps\b",
    re.IGNORECASE,
)

# Website watermark prefixes
_URL_WATERMARK_RE = re.compile(
    r"^(?:www\.[\w\-]+\.[\w]{2,6}|[\w\-]+\.(?:com|net|org|io|tv|me))"
    r"[\s._\-]*(?:-\s*)?",
    re.IGNORECASE,
)

# Separator-delimited watermark: "SomeGroup - Actual Title"
_LEADING_TAG_RE = re.compile(
    r"^[\w\.\s]{1,40}\s+-\s+",
    re.IGNORECASE,
)

# Junk tokens to strip from filenames
_JUNK_TOKENS = re.compile(
    r"\b("
    # Resolution
    r"2160p|1080p|1080i|720p|576p|480p|4k|uhd"
    # HDR
    r"|hdr|hdr10|hdr10\+|dv|dolby[\._\s]?vision|hlg"
    # Source
    r"|bluray|blu[\._\-]?ray|bdrip|bdremux|bdmux"
    r"|web[\._\-]?dl|webrip|web|amzn|nf|hmax|dsnp|atvp|pcok"
    r"|hdtv|dvdrip|dvdscr|dvd|ts|cam|r5|scr"
    # Video codec
    r"|hevc|x265|x264|h264|h265|avc|xvid|divx|av1|vp9|vp8"
    r"|10[\._\-]?bit|10bit|8bit|12bit|hq"
    # Audio codec
    r"|aac|dts|truehd|atmos|dd5\.1|dd2\.0|ac3|eac3|opus|flac|mp3|lpcm|pcm"
    r"|dolby|dolby[\._\s]?digital|dolby[\._\s]?atmos"
    # Release type
    r"|remux|repack|proper|extended|theatrical|directors[\._\s]?cut|unrated|retail"
    r"|internal|limited|complete|season|episode"
    # Common release groups
    r"|yts|yify|rarbg|eztv|ettv|mkvcage|sparks|fgt|ntb|nf|ion10"
    r"|tigole|qxr|bhdstudio|framestor|cinemageddon"
    # Generic noise
    r"|sample|trailer|featurette|extras?"
    r")\b",
    re.IGNORECASE,
)

_PUNCT_RE = re.compile(r"[\.\-_]+")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")
_BRACKETS_RE = re.compile(r"[\[\](){}<>]")
_TRAILING_NOISE_RE = re.compile(r"\s+[a-zA-Z0-9]{8,}\s*$")


# ── Pure functions ───────────────────────────────────────────────────────────

def _strip_watermark(text: str) -> str:
    """Strip website/group watermarks that appear before the real title."""
    cleaned = _URL_WATERMARK_RE.sub("", text).strip()
    if cleaned != text:
        return cleaned
    m = _LEADING_TAG_RE.match(text)
    if m:
        candidate = text[m.end():].strip()
        if len(candidate) >= 3:
            return candidate
    return text


def clean_filename(raw: str) -> str:
    """
    Clean a raw filename into a human-readable title.

    Pure function — no side effects, no filesystem access, independently testable.
    """
    # Start from basename without extension
    name = os.path.splitext(os.path.basename(raw))[0]

    # Strip watermarks
    name = _strip_watermark(name)

    # Replace dots/underscores/dashes with spaces
    name = _PUNCT_RE.sub(" ", name)
    # Remove brackets
    name = _BRACKETS_RE.sub(" ", name)

    # Find the year's position and truncate everything after it
    m = _YEAR_RE.search(name)
    if m:
        name = name[: m.start()].strip()
    else:
        # No year found — strip junk tokens instead
        name = _JUNK_TOKENS.sub("", name)

    name = _MULTI_SPACE_RE.sub(" ", name).strip(" -_.")

    # Title-case the result
    result = name.title() if name else raw.strip()

    # Truncate absurdly long titles
    if len(result) > 120:
        result = result[:120].rsplit(" ", 1)[0]

    return result


# ── Field extractors (each catches its own errors) ──────────────────────────

def _extract_codec(filename: str) -> str:
    try:
        m = _CODEC_RE.search(filename)
        if m:
            raw = m.group(1).lower()
            # Normalise common variants
            norm = {"x265": "h265", "x264": "h264", "h.265": "h265", "h.264": "h264"}
            return norm.get(raw, raw)
    except Exception:  # noqa: BLE001
        pass
    return UNKNOWN_SENTINEL


def _extract_format(filename: str) -> str:
    try:
        m = _FORMAT_RE.search(filename)
        if m:
            raw = m.group(1).lower().replace(".", "").replace("-", "").replace("_", "")
            return raw
    except Exception:  # noqa: BLE001
        pass
    return UNKNOWN_SENTINEL


def _extract_resolution(filename: str) -> str:
    try:
        m = _RESOLUTION_RE.search(filename)
        if m:
            raw = m.group(1).lower()
            res_map = {
                "2160p": "3840x2160", "4k": "3840x2160", "uhd": "3840x2160",
                "1080p": "1920x1080", "1080i": "1920x1080",
                "720p": "1280x720",
                "576p": "720x576",
                "480p": "720x480",
            }
            return res_map.get(raw, raw)
    except Exception:  # noqa: BLE001
        pass
    return UNKNOWN_SENTINEL


def _extract_framerate(filename: str) -> str:
    try:
        m = _FRAMERATE_RE.search(filename)
        if m:
            return m.group(1)
    except Exception:  # noqa: BLE001
        pass
    return UNKNOWN_SENTINEL


# ── Main classifier ─────────────────────────────────────────────────────────

def classify(filename: str) -> DeclaredMetadata:
    """
    Classify a raw filename into declared metadata.

    Input:  raw filename string (not a full path — just the filename)
    Output: DeclaredMetadata dataclass — never None, never a dict.
            Failed fields are set to the Unknown sentinel.
    No exceptions escape this function.
    """
    try:
        result = DeclaredMetadata(
            codec=_extract_codec(filename),
            format=_extract_format(filename),
            resolution=_extract_resolution(filename),
            framerate=_extract_framerate(filename),
            # SAR and DAR are rarely in filenames — default to Unknown
            sar=UNKNOWN_SENTINEL,
            dar=UNKNOWN_SENTINEL,
        )
    except Exception:  # noqa: BLE001
        # Total failure — return all-Unknown
        result = DeclaredMetadata()

    # <telemetry>: classifier_result(uuid=<caller-provides>, declared_fields_parsed=N, fields_unknown=N)
    #   — emitted by the caller since classifier doesn't know the uuid
    return result
