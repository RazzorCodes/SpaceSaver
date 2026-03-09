import subprocess
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import ffmpeg
from models.models import ListItem
from models.orm import WorkItemStatus


def check_executable() -> bool:
    try:
        subprocess.run(
            ["ffprobe", "-h"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return True
    except FileNotFoundError:
        return False


def inspect(item: ListItem):
    try:
        meta = ffmpeg.probe(item.path)
        format_info = meta["format"]
        
        video_stream = next(
            (s for s in meta["streams"] if s.get("codec_type") == "video"),
            None,
        )
        if video_stream is None:
            raise RuntimeError(f"No video stream found in {item.name}")
            
        rate = (
            video_stream.get("avg_frame_rate")
            or video_stream.get("r_frame_rate")
            or "0/1"
        )
        try:
            framerate = 0.0 if rate == "0/0" else float(Fraction(rate))
        except (ZeroDivisionError, ValueError):
            framerate = 0.0

        size = Path(item.path).stat().st_size

        item = replace(
            item,
            status=WorkItemStatus.PENDING,
            size=size,
            duration=float(format_info["duration"]),
            codec=video_stream["codec_name"],
            resolution=(video_stream["width"], video_stream["height"]),
            sar=video_stream.get("sample_aspect_ratio"),
            dar=video_stream.get("display_aspect_ratio"),
            framerate=framerate,
            # audio=audio_streams,
        )
    except ffmpeg.Error as e:
        # THE FIX: Extract and decode the actual error from the ffmpeg binary
        error_detail = (
            e.stderr.decode("utf-8", errors="ignore")
            if e.stderr
            else "No stderr output"
        )
        raise RuntimeError(
            f"ffprobe actually crashed on {item.name} because:\n{error_detail}"
        )

    return item
