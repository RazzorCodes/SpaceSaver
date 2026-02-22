"""
prober.py — Media probing utility for SpaceSaver.

Uses ffprobe to extract ACTUAL metadata from media files.
"""

from __future__ import annotations

import logging
import ffmpeg
from models import Metadata, MetadataKind, UNKNOWN_SENTINEL

log = logging.getLogger(__name__)


def extract_actual_metadata(uuid: str, path: str) -> Metadata:
    """
    Probe a media file using ffprobe and extract ACTUAL metadata.
    Defensively parses video stream properties.
    Returns a Metadata row with kind=MetadataKind.ACTUAL.
    """
    meta = Metadata(uuid=uuid, kind=MetadataKind.ACTUAL)

    try:
        probe = ffmpeg.probe(path)
    except ffmpeg.Error as exc:
        log.warning("[prober] ffprobe failed for %s (uuid=%s): %s", path, uuid, exc)
        return meta
    except Exception as exc:
        log.warning("[prober] unexpected error probing %s (uuid=%s): %s", path, uuid, exc)
        return meta

    streams = probe.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]

    if not video_streams:
        log.debug("[prober] no video streams found for %s", path)
        return meta

    # Pick the first video stream (usually the main one)
    vs = video_streams[0]

    meta.codec = vs.get("codec_name", UNKNOWN_SENTINEL)
    meta.format = vs.get("pix_fmt", UNKNOWN_SENTINEL)

    # Resolution
    width = vs.get("width")
    height = vs.get("height")
    if width and height:
        meta.resolution = f"{width}x{height}"

    # Aspect Ratios
    # Sometimes present as sample_aspect_ratio / display_aspect_ratio
    # ffmpeg-python parses them as strings like "1:1" or "16:9"
    sar = vs.get("sample_aspect_ratio")
    if sar and sar != "0:1":
        meta.sar = sar

    dar = vs.get("display_aspect_ratio")
    if dar and dar != "0:1":
        meta.dar = dar

    # Framerate (r_frame_rate is usually "24000/1001" or "25/1")
    fps_str = vs.get("r_frame_rate")
    if fps_str:
        try:
            num, den = fps_str.split("/")
            if int(den) != 0:
                meta.framerate = round(float(num) / float(den), 3)
        except Exception:
            pass

    # You could also grab duration, bitrate from format info if needed
    fmt_info = probe.get("format", {})
    try:
        duration = float(fmt_info.get("duration", 0))
        bitrate = int(fmt_info.get("bit_rate", 0))
        if duration > 0:
            meta.extra["duration"] = duration
        if bitrate > 0:
            meta.extra["bitrate"] = bitrate
    except Exception:
        pass

    return meta
