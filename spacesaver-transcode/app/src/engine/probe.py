from pathlib import Path

import ffmpeg

from app.src.models.orm import Metadata


def probe_file(path: Path) -> Metadata:

    meta = ffmpeg.probe("input.mp4")

    format_info = meta["format"]
    video_stream = next(s for s in meta["streams"] if s["codec_type"] == "video")
    audio_streams = [s.__str__() for s in meta["streams"] if s["codec_type"] == "audio"]

    return Metadata(
        size=path.stat().st_size,
        duration=float(format_info["duration"]),
        codec=video_stream["codec_name"],
        resolution=(video_stream["width"], video_stream["height"]),
        sar=video_stream.get("sample_aspect_ratio"),
        dar=video_stream.get("display_aspect_ratio"),
        framerate=eval(video_stream["avg_frame_rate"]),
        audio=audio_streams,
    )
