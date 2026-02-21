"""
classifier.py — Determine media type, extract clean title, and derive year/episode string.

Classification logic:
  - TV: path contains an episode pattern (S##E##, s##e##) OR a season folder
        (Season XX, Specials, etc.)
  - Movie: everything else

Title extraction (in priority order):
  1. 'title' tag from MKV/container metadata via ffprobe (stripped of junk)
  2. Filename-based cleaning: strip codec, resolution, source, release-group tokens
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

# Episode detection: e.g. S01E03, s02e14, Season 2
_EP_PATTERN = re.compile(
    r"[Ss]\d{1,2}[Ee]\d{1,2}"          # S01E03
    r"|[Ss]eason\s*\d{1,2}"             # Season 2
    r"|/[Ss]eason[\s._-]*\d{1,2}/",     # /Season 02/
    re.IGNORECASE,
)

# Episode label extraction: returns (S01E03) or (S01) and episode context
_EP_LABEL_RE = re.compile(r"([Ss]\d{1,2}[Ee]\d{1,2})", re.IGNORECASE)
_SEASON_LABEL_RE = re.compile(r"[Ss]eason[\s._-]*(\d{1,2})", re.IGNORECASE)

# Year extraction from titles / filenames
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# Junk tokens to strip from filenames (order matters — longest first)
_JUNK_TOKENS = re.compile(
    r"\b("
    r"2160p|1080p|1080i|720p|576p|480p"          # resolution
    r"|4k|uhd|hdr|hdr10|hdr10\+|dv|dolby.?vision"
    r"|bluray|blu-ray|bdrip|bdremux|bdmux"        # source
    r"|web-?dl|webrip|web|amzn|nf|hmax|dsnp|atvp"
    r"|hdtv|dvdrip|dvdscr|ts|cam"
    r"|hevc|x265|x264|h264|h265|avc|xvid|divx"   # codec
    r"|aac|dts|truehd|atmos|dd5\.1|ac3|eac3|opus|flac|mp3"  # audio
    r"|remux|repack|proper|extended|theatrical|directors.cut"
    r"|yts|yify|rarbg|eztv|ettv|mkvcage|sparks"  # release groups
    r"|sample"
    r")\b",
    re.IGNORECASE,
)

_PUNCT_JUNK_RE = re.compile(r"[\.\-_]+")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")
_BRACKETS_RE = re.compile(r"[\[\](){}<>]")


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


def _clean_from_filename(path: str) -> str:
    """Derive a clean title from the bare filename."""
    name = os.path.splitext(os.path.basename(path))[0]
    # Replace dots/underscores/dashes between words with spaces
    name = _PUNCT_JUNK_RE.sub(" ", name)
    # Remove bracket groups entirely
    name = _BRACKETS_RE.sub(" ", name)
    # Remove junk tokens
    name = _JUNK_TOKENS.sub("", name)
    # Remove leftover year (we'll re-extract it separately)
    name = _YEAR_RE.sub("", name)
    name = _MULTI_SPACE_RE.sub(" ", name).strip()
    return name.title()


def _clean_tag_title(raw: str) -> str:
    """Light cleaning of a metadata title (usually already human-readable)."""
    cleaned = _JUNK_TOKENS.sub("", raw)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned).strip()
    return cleaned or raw.strip()


def _extract_year(path: str, title: str) -> Optional[str]:
    # Try filename first
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

    # Truncate absurdly long titles (metadata can sometimes be full plot summaries)
    if len(clean_title) > 120:
        clean_title = clean_title[:120].rsplit(" ", 1)[0]

    # --- Year / Episode ---
    if is_tv:
        year_or_episode = _extract_episode(path) or ""
    else:
        year_or_episode = _extract_year(path, clean_title) or ""

    return media_type, clean_title, year_or_episode
