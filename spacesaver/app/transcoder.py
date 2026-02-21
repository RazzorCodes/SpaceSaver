"""
transcoder.py — Background thread that encodes PENDING files one at a time.

Responsibilities:
  - Pick next PENDING file from the DB
  - Build an ffmpeg-python pipeline:
      - Scale video to resolution cap
      - Encode with libx265 at the appropriate CRF
      - Copy existing lossy audio tracks (AAC, AC3, EAC3, DTS, MP3, Opus)
      - Re-encode uncompressed/lossless audio (PCM, TrueHD, FLAC) to
          AAC (surround ≥3 channels) or Opus (stereo/mono)
      - Copy all subtitle streams unchanged
  - Write to /workdir/<uuid>.mkv, then atomically move to /dest/... on success
  - Retry once on failure; mark ERROR after two failures
  - Persist IN_PROGRESS state to a progress JSON for crash recovery
  - Append successful file hash to the flat file
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from typing import Optional

import ffmpeg

import db
from config import cfg
from models import FileStatus, MediaFile, MediaType

log = logging.getLogger(__name__)

WORKDIR = "/workdir"
DEST_DIR = "/dest"
FLAT_FILE = os.path.join(DEST_DIR, ".spacesaver-transcode")
PROGRESS_DIR = "/dest/.transcoder/progress"

# Audio codecs considered lossless / uncompressed → need re-encoding
_LOSSLESS_CODECS = {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le",
                    "truehd", "mlp", "flac", "dts-hd ma", "dts ma"}

_stop_event = threading.Event()
_current_file: Optional[MediaFile] = None
_current_lock = threading.Lock()


def get_current_file() -> Optional[MediaFile]:
    with _current_lock:
        return _current_file


def _set_current(mf: Optional[MediaFile]) -> None:
    global _current_file  # noqa: PLW0603
    with _current_lock:
        _current_file = mf


def _write_progress_json(mf: MediaFile) -> None:
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    data = {
        "uuid": mf.uuid,
        "source_path": mf.source_path,
        "dest_path": mf.dest_path,
        "status": mf.status.value,
    }
    path = os.path.join(PROGRESS_DIR, f"{mf.uuid}.json")
    with open(path, "w") as f:
        json.dump(data, f)


def _remove_progress_json(uuid: str) -> None:
    path = os.path.join(PROGRESS_DIR, f"{uuid}.json")
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _cleanup_workdir(uuid: str) -> None:
    tmp = os.path.join(WORKDIR, f"{uuid}.mkv")
    try:
        os.remove(tmp)
    except FileNotFoundError:
        pass


def _append_flat_file(file_hash: str) -> None:
    try:
        with open(FLAT_FILE, "a") as f:
            f.write(file_hash + "\n")
    except OSError as exc:
        log.error("Could not append to flat file: %s", exc)


def _probe_streams(source_path: str) -> list:
    """Return list of stream dicts from ffprobe."""
    try:
        probe = ffmpeg.probe(source_path)
        return probe.get("streams", [])
    except ffmpeg.Error as exc:
        log.error("ffprobe failed for %s: %s", source_path, exc)
        return []


def _is_lossless(codec_name: str) -> bool:
    return codec_name.lower() in _LOSSLESS_CODECS or codec_name.lower().startswith("pcm_")


def _effective_crf(mf: MediaFile) -> int:
    if mf.media_type == MediaType.TV:
        return mf.tv_crf if mf.tv_crf is not None else cfg.tv_crf
    return mf.movie_crf if mf.movie_crf is not None else cfg.movie_crf


def _effective_res_cap(mf: MediaFile) -> int:
    if mf.media_type == MediaType.TV:
        return mf.tv_res_cap if mf.tv_res_cap is not None else cfg.tv_res_cap
    return mf.movie_res_cap if mf.movie_res_cap is not None else cfg.movie_res_cap


def _build_ffmpeg(mf: MediaFile, tmp_path: str, streams: list) -> ffmpeg.nodes.OutputStream:
    """Construct the ffmpeg-python output stream."""
    crf = _effective_crf(mf)
    res_cap = _effective_res_cap(mf)

    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

    inp = ffmpeg.input(mf.source_path)

    output_streams = []

    # --- Video ---
    for i, vs in enumerate(video_streams):
        width = vs.get("width", 0)
        height = vs.get("height", 0)
        vstream = inp[f"v:{i}"]
        if height > res_cap and res_cap > 0:
            # Scale to res_cap, preserving aspect ratio, force even dimensions
            vstream = vstream.filter("scale", -2, res_cap)
        vstream = vstream.video.filter(
            "scale",
            w="trunc(iw/2)*2",
            h="trunc(ih/2)*2",
        )
        output_streams.append(vstream)

    # --- Audio ---
    audio_output_codecs = []
    for i, ast in enumerate(audio_streams):
        codec = ast.get("codec_name", "").lower()
        channels = ast.get("channels", 2)
        astream = inp[f"a:{i}"]
        if _is_lossless(codec):
            if channels >= 3:
                enc = "aac"
                opts = {"b:a": "640k"}
            else:
                enc = "libopus"
                opts = {"b:a": "192k"}
            audio_output_codecs.append((astream, enc, opts))
        else:
            audio_output_codecs.append((astream, "copy", {}))
        output_streams.append(astream)

    # --- Subtitles ---
    for i, _ in enumerate(subtitle_streams):
        output_streams.append(inp[f"s:{i}"])

    # Build codec arguments
    codec_args: dict = {
        "vcodec": "libx265",
        "crf": crf,
        "preset": "slow",
        "x265-params": "log-level=error",
        "acodec": "copy",  # default
        "scodec": "copy",
    }

    # Per-stream audio codec overrides
    for idx, (_, enc, opts) in enumerate(audio_output_codecs):
        if enc != "copy":
            codec_args[f"codec:a:{idx}"] = enc
            for k, v in opts.items():
                codec_args[f"{k}:{idx}"] = v

    out = ffmpeg.output(
        *output_streams,
        tmp_path,
        **codec_args,
        format="matroska",
    )
    return out.overwrite_output()


def _progress_callback(uuid: str, total_frames: int):
    """Returns a callable that ffmpeg reports progress to (via stderr parse)."""
    # ffmpeg-python doesn't have a native progress hook; we use the
    # stats_period pattern via ffmpeg's own -progress pipe.
    # Progress is updated by _encode() based on elapsed time heuristics instead.
    pass


def _encode(mf: MediaFile) -> bool:
    """
    Actually run ffmpeg. Returns True on success.
    Progress is estimated from ffmpeg's stderr frame counter.
    """
    tmp_path = os.path.join(WORKDIR, f"{mf.uuid}.mkv")
    streams = _probe_streams(mf.source_path)
    if not streams:
        raise RuntimeError("ffprobe returned no streams")

    # Estimate total frames for progress
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    total_frames = 0
    for vs in video_streams:
        fps_str = vs.get("r_frame_rate", "25/1")
        try:
            num, den = fps_str.split("/")
            fps = float(num) / float(den)
        except Exception:  # noqa: BLE001
            fps = 25.0
        duration = float(vs.get("duration", 0) or 0)
        if duration <= 0:
            # Try container duration
            pass
        total_frames += int(fps * duration)

    out_stream = _build_ffmpeg(mf, tmp_path, streams)

    # Run with progress tracking via ffmpeg -progress pipe
    process = (
        out_stream
        .global_args("-progress", "pipe:1", "-nostats")
        .run_async(pipe_stdout=True, pipe_stderr=True)
    )

    frames_done = 0
    while True:
        line = process.stdout.readline()
        if not line:
            break
        line = line.decode("utf-8", errors="ignore").strip()
        if line.startswith("frame="):
            try:
                frames_done = int(line.split("=")[1])
            except ValueError:
                pass
            if total_frames > 0:
                progress = min(99.0, (frames_done / total_frames) * 100)
            else:
                progress = 50.0  # unknown total
            db.update_progress(mf.uuid, progress)

    process.wait()
    if process.returncode != 0:
        stderr_out = process.stderr.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"ffmpeg exited {process.returncode}: {stderr_out[-500:]}")

    return True


def _process_file(mf: MediaFile) -> None:
    tmp_path = os.path.join(WORKDIR, f"{mf.uuid}.mkv")
    dest_dir = os.path.dirname(mf.dest_path)

    db.update_status(mf.uuid, FileStatus.IN_PROGRESS, 0.0)
    mf.status = FileStatus.IN_PROGRESS
    _write_progress_json(mf)
    _set_current(mf)
    log.info("Encoding: %s → %s", mf.source_path, mf.dest_path)

    try:
        _encode(mf)

        # Move to final destination
        os.makedirs(dest_dir, exist_ok=True)
        shutil.move(tmp_path, mf.dest_path)

        db.update_status(mf.uuid, FileStatus.DONE, 100.0)
        _append_flat_file(mf.file_hash)
        _remove_progress_json(mf.uuid)
        log.info("Done: %s", mf.dest_path)

    except Exception as exc:  # noqa: BLE001
        _cleanup_workdir(mf.uuid)
        error_msg = str(exc)
        # Check retry count
        fresh = db.get_by_uuid(mf.uuid)
        error_count = (fresh.error_count if fresh else 0)
        if error_count < 1:
            # First failure — update error count, requeue as PENDING
            db.update_error(mf.uuid, error_msg)
            db.update_status(mf.uuid, FileStatus.PENDING, 0.0)
            log.warning("Encode failed (will retry once): %s — %s", mf.clean_title, error_msg)
        else:
            # Second failure — mark as ERROR permanently
            db.update_error(mf.uuid, error_msg)
            log.error("Encode failed permanently: %s — %s", mf.clean_title, error_msg)

        _remove_progress_json(mf.uuid)

    finally:
        _set_current(None)


def _on_startup_cleanup() -> None:
    """Clean up any leftover workdir temp files from a previous crash."""
    try:
        for fname in os.listdir(WORKDIR):
            if fname.endswith(".mkv"):
                path = os.path.join(WORKDIR, fname)
                log.warning("Removing leftover temp file: %s", path)
                os.remove(path)
    except OSError:
        pass
    # Reset any IN_PROGRESS rows
    db.reset_in_progress()


def run() -> None:
    """Entry point for the transcoder background thread."""
    _on_startup_cleanup()
    log.info("Transcoder started. Workdir: %s", WORKDIR)
    while not _stop_event.is_set():
        pending = db.list_by_status(FileStatus.PENDING)
        if not pending:
            _stop_event.wait(10)
            continue
        mf = pending[0]
        try:
            _process_file(mf)
        except Exception as exc:  # noqa: BLE001
            log.exception("Unexpected transcoder error: %s", exc)
            _stop_event.wait(5)
    log.info("Transcoder stopped.")


def start() -> threading.Thread:
    t = threading.Thread(target=run, name="transcoder", daemon=True)
    t.start()
    return t


def stop() -> None:
    _stop_event.set()
