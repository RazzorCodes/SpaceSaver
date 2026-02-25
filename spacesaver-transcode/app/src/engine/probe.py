import subprocess
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import ffmpeg
from models.models import ListItem


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


from dataclasses import asdict


def inspect(item: ListItem):
    meta = ffmpeg.probe(item.path)
    format_info = meta["format"]
    video_stream = next(s for s in meta["streams"] if s["codec_type"] == "video")
    audio_streams = [str(s) for s in meta["streams"] if s["codec_type"] == "audio"]

    framerate = float(Fraction(video_stream["avg_frame_rate"]))

    size = Path(item.path).stat().st_size

    item = replace(
        item,
        status="pending",
        size=size,
        duration=float(format_info["duration"]),
        codec=video_stream["codec_name"],
        resolution=(video_stream["width"], video_stream["height"]),
        sar=video_stream.get("sample_aspect_ratio"),
        dar=video_stream.get("display_aspect_ratio"),
        framerate=framerate,
        # audio=audio_streams,
    )

    return item
