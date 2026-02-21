"""
classifier.py — Determine media type, extract clean title, and derive year/episode string.

Classification logic:
  - TV: path contains an episode pattern (S##E##, s##e##) OR a season folder
  - Movie: everything else

Title extraction (in priority order):
  1. 'title' tag from MKV/container metadata via ffprobe (stripped of junk + watermarks)
  2. Filename-based cleaning: strip all junk tokens, then truncate at the year
     (everything after the year in a filename is release group noise)
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from typing import Optional, Tuple

from models import MediaType

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

# Website watermark prefixes: "www.something.org", "www.something.com - "
# Also handles IP or plain domain watermarks like "domain.tld - Title"
_URL_WATERMARK_RE = re.compile(
    r"^(?:www\.[\w\-]+\.[\w]{2,6}|[\w\-]+\.(?:com|net|org|io|tv|me))"
    r"[\s._\-]*(?:-\s*)?",
    re.IGNORECASE,
)

# Separator-delimited watermark: "SomeGroup - Actual Title"
# Remove a leading segment followed by " - " if it looks like a group/URL
_LEADING_TAG_RE = re.compile(
    r"^[\w\.\s]{1,40}\s+-\s+",
    re.IGNORECASE,
)

# Junk tokens to strip from filenames and metadata titles
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
    # Common release groups (can't catch all, but hit the most common)
    r"|yts|yify|rarbg|eztv|ettv|mkvcage|sparks|fgt|ntb|nf|ion10"
    r"|tigole|qxr|bhdstudio|framestor|cinemageddon|framestor"
    # Generic noise
    r"|sample|trailer|featurette|extras?"
    r")\b",
    re.IGNORECASE,
)

_PUNCT_RE = re.compile(r"[\.\-_]+")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")
_BRACKETS_RE = re.compile(r"[\[\](){}<>]")
# Trailing noise: sequences of numbers/letters that look like hashes or IDs
_TRAILING_NOISE_RE = re.compile(r"\s+[a-zA-Z0-9]{8,}\s*$")


def _probe_title(path: str) -> Optional[str]:
    """Read the 'title' metadata tag from the container using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        raw = data.get("format", {}).get("tags", {}).get("title", "")
        return raw.strip() or None
    except Exception as exc:  # noqa: BLE001
        log.debug("ffprobe title extraction failed for %s: %s", path, exc)
        return None


def _strip_watermark(text: str) -> str:
    """
    Strip website/group watermarks that appear before the real title.
    Handles patterns like:
      - "www.UIndex.org - Harry Potter..."
      - "SomeGroup - Movie Title"
    """
    # Try explicit URL prefix first
    cleaned = _URL_WATERMARK_RE.sub("", text).strip()
    if cleaned != text:
        return cleaned
    # Try "Word(s) - Title" pattern only if the leading segment is short
    # and doesn't look like it's part of a real title
    m = _LEADING_TAG_RE.match(text)
    if m:
        candidate = text[m.end():].strip()
        # Only strip if the remaining text is plausibly a title (≥3 chars)
        if len(candidate) >= 3:
            return candidate
    return text


def _clean_tag_title(raw: str) -> str:
    """Clean a metadata title tag."""
    text = raw.strip()
    # Strip website/group watermarks
    text = _strip_watermark(text)
    # Strip junk codec/source tokens
    text = _JUNK_TOKENS.sub("", text)
    # Strip year (stored separately as year_or_episode)
    text = _YEAR_RE.sub("", text)
    # Strip leftover brackets and punctuation runs
    text = _BRACKETS_RE.sub(" ", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip(" -_.")
    return text or raw.strip()


def _clean_from_filename(path: str) -> str:
    """
    Derive a clean title from the filename.

    Key insight: in media filenames, everything after the year (or after junk
    codec/source tokens start) is release group noise. We truncate there.
    """
    name = os.path.splitext(os.path.basename(path))[0]

    # Replace dots/underscores/dashes with spaces
    name = _PUNCT_RE.sub(" ", name)
    # Remove brackets and their contents — usually tags like [YTS], (2022)
    name = _BRACKETS_RE.sub(" ", name)

    # Find the year's position and truncate everything after it
    m = _YEAR_RE.search(name)
    if m:
        # Keep only the part before the year (year itself is stored separately)
        name = name[: m.start()].strip()
    else:
        # No year found — strip junk tokens instead
        name = _JUNK_TOKENS.sub("", name)

    name = _MULTI_SPACE_RE.sub(" ", name).strip(" -_.")
    return name.title()


def _extract_year(path: str, title: str) -> Optional[str]:
    """Find a year in the path or title."""
    for text in (os.path.basename(path), title):
        m = _YEAR_RE.search(text)
        if m:
            return m.group(0)
    return None


def _extract_episode(path: str) -> Optional[str]:
    m = _EP_LABEL_RE.search(path)
    if m:
        return m.group(1).upper()   # e.g. S01E03
    m = _SEASON_LABEL_RE.search(path)
    if m:
        return f"S{int(m.group(1)):02d}"
    return None


def classify(path: str) -> Tuple[MediaType, str, str]:
    """
    Returns (media_type, clean_title, year_or_episode).

    year_or_episode examples:
      Movie: "2001"
      TV:    "S01E03" or "S02"
    """
    is_tv = bool(_EP_PATTERN.search(path))
    media_type = MediaType.TV if is_tv else MediaType.MOVIE

    # --- Title ---
    raw_tag = _probe_title(path)
    if raw_tag:
        clean_title = _clean_tag_title(raw_tag)
    else:
        clean_title = _clean_from_filename(path)

    # Truncate absurdly long titles
    if len(clean_title) > 120:
        clean_title = clean_title[:120].rsplit(" ", 1)[0]

    # --- Year / Episode ---
    if is_tv:
        year_or_episode = _extract_episode(path) or ""
    else:
        year_or_episode = _extract_year(path, clean_title) or ""

    return media_type, clean_title, year_or_episode
