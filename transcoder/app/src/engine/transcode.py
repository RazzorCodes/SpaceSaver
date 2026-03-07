import subprocess
import threading
from pathlib import Path
from typing import Callable

import ffmpeg


def get_total_frames(input_path: str | Path) -> int:
    """Helper: Uses ffprobe to estimate total video frames for progress percentage."""
    try:
        probe = ffmpeg.probe(str(input_path))
        video_streams = [
            s for s in probe.get("streams", []) if s.get("codec_type") == "video"
        ]

        total_frames = 0
        for vs in video_streams:
            fps_str = vs.get("r_frame_rate", "25/1")
            try:
                num, den = fps_str.split("/")
                fps = float(num) / float(den) if float(den) else 25.0
            except Exception:
                fps = 25.0

            duration = float(vs.get("duration") or 0)
            total_frames += int(fps * duration)

        if total_frames == 0:  # Fallback to container duration
            dur = float(probe.get("format", {}).get("duration", 0) or 0)
            total_frames = int(dur * 25)

        return total_frames
    except Exception:
        return 0


def transcode_file(
    input_path: Path | str,
    output_path: Path | str,
    video_codec: str = "libx265",
    crf: int = 22,
    preset: str = "slow",
    audio_codec: str = "aac",
    audio_bitrate: str = "192k",
    resolution_cap: int | None = None,
    progress_callback: Callable[[float, int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """
    Transcodes a media file using ffmpeg. Blocks until complete.
    Reports real-time progress via the provided callback function.
    """
    input_str = str(input_path)
    output_str = str(output_path)

    total_frames = get_total_frames(input_str)

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        input_str,
        "-map",
        "0:v?",
        "-map",
        "0:a?",
        "-map",
        "0:s?",
        "-c:v",
        video_codec,
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-c:a",
        audio_codec,
        "-b:a",
        audio_bitrate,
        "-c:s",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        "-f",
        "matroska",
        output_str,
    ]

    if resolution_cap:
        cmd += ["-vf", f"scale=-2:{resolution_cap}"]

    # 1. Launch ffmpeg
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1,
    )

    # 2. Dedicated killer function to watch the abort flag
    def kill_if_cancelled():
        while process.poll() is None:
            if cancel_event and cancel_event.wait(timeout=0.5):
                process.kill()
                break

    # 3. Start the watcher immediately
    if cancel_event:
        killer_thread = threading.Thread(target=kill_if_cancelled, daemon=True)
        killer_thread.start()

    # 4. Progress loop
    if process.stdout:
        for line in process.stdout:
            line = line.strip()
            if line.startswith("frame="):
                try:
                    frames_done = int(line.split("=", 1)[1].strip())
                except ValueError:
                    continue

                if progress_callback:
                    pct = (
                        (frames_done / total_frames * 100.0)
                        if total_frames > 0
                        else 0.0
                    )
                    pct = min(99.9, pct)
                    progress_callback(pct, frames_done, total_frames)

    process.wait()

    # 5. Check exit states
    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Transcoding was cancelled.")

    if process.returncode != 0:
        stderr_out = process.stderr.read() if process.stderr else "Unknown error"
        raise RuntimeError(
            f"ffmpeg exited with code {process.returncode}:\n{stderr_out.strip()}"
        )

    if progress_callback:
        progress_callback(100.0, total_frames, total_frames)
