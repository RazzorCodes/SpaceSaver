"""
transcoder.py — Background thread that encodes PENDING files one at a time.

Responsibilities:
  - Pick next PENDING file from the DB
  - Build and run an ffmpeg subprocess:
      - Scale video to resolution cap (only if source exceeds it)
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
import subprocess
import threading
import time
from typing import Optional, Tuple

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
_LOSSLESS_CODECS = {
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_s16be",
    "pcm_s24be", "pcm_s32be", "pcm_f64le", "pcm_f64be",
    "truehd", "mlp", "flac",
}

# Source video codecs that are already HEVC — re-encoding would lose quality
_HEVC_CODECS = {"hevc", "h265"}

# Conservative CRF → max expected bitrate (kbps) at 1080p for libx265.
# If the source is already *below* this threshold (normalised to 1080p)
# the encode would produce a larger or identical file — skip it.
_CRF_BITRATE_TABLE = {
    16: 8000,
    18: 5500,
    20: 3800,
    22: 2500,
    24: 1700,
    26: 1200,
    28:  800,
}
_CRF_BITRATE_DEFAULT = 5500  # fallback for CRF values not in the table
_PIXELS_1080P = 1920 * 1080

_stop_event = threading.Event()
_current_file: Optional[MediaFile] = None
_current_start_time: float = 0.0
_current_frame_now: int = 0
_current_frame_total: int = 0
_current_lock = threading.Lock()


def get_current_info() -> Tuple[Optional[MediaFile], float, int, int]:
    with _current_lock:
        return _current_file, _current_start_time, _current_frame_now, _current_frame_total


def get_current_file() -> Optional[MediaFile]:
    with _current_lock:
        return _current_file


def _set_current(mf: Optional[MediaFile], total_frames: int = 0) -> None:
    global _current_file, _current_start_time, _current_frame_now, _current_frame_total  # noqa: PLW0603
    with _current_lock:
        _current_file = mf
        _current_start_time = time.time() if mf is not None else 0.0
        _current_frame_now = 0
        _current_frame_total = total_frames


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
    name = codec_name.lower()
    return name in _LOSSLESS_CODECS or name.startswith("pcm_")


def _is_dts_hd(codec_name: str, profile: str) -> bool:
    """DTS-HD MA and DTS:X are lossless; plain DTS is lossy."""
    name = codec_name.lower()
    prof = (profile or "").lower()
    if name != "dts":
        return False
    return "ma" in prof or "hd" in prof or "x" in prof


def _effective_crf(mf: MediaFile) -> int:
    if mf.media_type == MediaType.TV:
        return mf.tv_crf if mf.tv_crf is not None else cfg.tv_crf
    return mf.movie_crf if mf.movie_crf is not None else cfg.movie_crf


def _effective_res_cap(mf: MediaFile) -> int:
    if mf.media_type == MediaType.TV:
        return mf.tv_res_cap if mf.tv_res_cap is not None else cfg.tv_res_cap
    return mf.movie_res_cap if mf.movie_res_cap is not None else cfg.movie_res_cap


def _crf_bitrate_threshold(crf: int) -> int:
    """Return the 1080p bitrate ceiling (kbps) for a given CRF value."""
    if crf in _CRF_BITRATE_TABLE:
        return _CRF_BITRATE_TABLE[crf]
    # Linear interpolation between the two nearest table entries
    lower = max((k for k in _CRF_BITRATE_TABLE if k <= crf), default=None)
    upper = min((k for k in _CRF_BITRATE_TABLE if k >= crf), default=None)
    if lower is None:
        return _CRF_BITRATE_TABLE[min(_CRF_BITRATE_TABLE)]
    if upper is None:
        return _CRF_BITRATE_TABLE[max(_CRF_BITRATE_TABLE)]
    lo_bps, hi_bps = _CRF_BITRATE_TABLE[lower], _CRF_BITRATE_TABLE[upper]
    ratio = (crf - lower) / (upper - lower)
    return int(lo_bps + ratio * (hi_bps - lo_bps))


def _should_skip(mf: MediaFile, streams: list, probe: dict) -> tuple[bool, str]:
    """
    Decide whether encoding this file would be wasteful.

    Returns (skip: bool, reason: str).
    """
    video_streams = [s for s in streams if s.get("codec_type") == "video"]

    # 1. Source is already HEVC — re-encoding is guaranteed quality loss.
    for vs in video_streams:
        codec = vs.get("codec_name", "").lower()
        if codec in _HEVC_CODECS:
            return True, "source is already HEVC/H.265"

    # 2. Source bitrate already below what the configured CRF would produce.
    try:
        source_kbps = int(probe.get("format", {}).get("bit_rate", 0)) // 1000
    except (TypeError, ValueError):
        source_kbps = 0

    if source_kbps > 0:
        # Normalise bitrate to 1080p-equivalent using the largest video stream
        max_pixels = max(
            (vs.get("width", 1920) * vs.get("height", 1080) for vs in video_streams),
            default=_PIXELS_1080P,
        )
        normalised_kbps = int(source_kbps * _PIXELS_1080P / max(max_pixels, 1))
        threshold = _crf_bitrate_threshold(_effective_crf(mf))
        if normalised_kbps < threshold:
            return (
                True,
                f"source bitrate {source_kbps} kbps (≈{normalised_kbps} kbps @1080p) "
                f"already below CRF {_effective_crf(mf)} threshold {threshold} kbps",
            )

    return False, ""


def _build_cmd(mf: MediaFile, tmp_path: str, streams: list) -> list:
    """
    Build the ffmpeg CLI command as a list of arguments.

    Uses -map to explicitly select streams rather than the ffmpeg-python node
    graph, which is error-prone when combining filtered and unfiltered streams.
    """
    crf = _effective_crf(mf)
    res_cap = _effective_res_cap(mf)

    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    video_streams = [s for s in streams if s.get("codec_type") == "video"]

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", mf.source_path,
        # Map all streams explicitly
        "-map", "0:v",    # all video tracks
        "-map", "0:a",    # all audio tracks
        "-map", "0:s?",   # all subtitle tracks (? = don't fail if none)
        # Video: libx265
        "-c:v", "libx265",
        "-crf", str(crf),
        "-preset", "slow",
        "-x265-params", "log-level=error",
    ]

    # Video scaling: only downscale if source height exceeds cap
    max_height = max((s.get("height", 0) for s in video_streams), default=0)
    if res_cap > 0 and max_height > res_cap:
        # scale=-2:H → ffmpeg computes width to maintain AR, rounded to even
        cmd += ["-vf", f"scale=-2:{res_cap}"]

    # Audio: per-stream codec selection
    any_lossless = any(
        _is_lossless(s.get("codec_name", "")) or
        _is_dts_hd(s.get("codec_name", ""), s.get("profile", ""))
        for s in audio_streams
    )

    if not any_lossless:
        # All lossy — bulk copy is safe and simpler
        cmd += ["-c:a", "copy"]
    else:
        for i, ast in enumerate(audio_streams):
            codec = ast.get("codec_name", "")
            profile = ast.get("profile", "")
            channels = ast.get("channels", 2)
            if _is_lossless(codec) or _is_dts_hd(codec, profile):
                if channels >= 3:
                    cmd += [f"-c:a:{i}", "aac", f"-b:a:{i}", "640k"]
                else:
                    cmd += [f"-c:a:{i}", "libopus", f"-b:a:{i}", "192k"]
            else:
                cmd += [f"-c:a:{i}", "copy"]

    # Subtitles: always copy
    cmd += ["-c:s", "copy"]

    # Progress reporting to stdout (parsed by _encode)
    cmd += ["-progress", "pipe:1", "-nostats"]

    # Output format and path
    cmd += ["-f", "matroska", tmp_path]

    return cmd


def _encode(mf: MediaFile, streams: list) -> None:
    """Run ffmpeg as a subprocess, updating progress in the DB from stdout."""
    tmp_path = os.path.join(WORKDIR, f"{mf.uuid}.mkv")

    # Estimate total frames for progress calculation
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    total_frames = 0
    for vs in video_streams:
        fps_str = vs.get("r_frame_rate", "25/1")
        try:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) else 25.0
        except Exception:  # noqa: BLE001
            fps = 25.0
        duration = 0.0
        try:
            duration = float(vs.get("duration") or 0)
        except (TypeError, ValueError):
            pass
        total_frames += int(fps * duration)

    # Also try container duration as fallback
    if total_frames == 0:
        try:
            probe = ffmpeg.probe(mf.source_path)
            dur = float(probe.get("format", {}).get("duration", 0) or 0)
            total_frames = int(dur * 25)  # rough estimate
        except Exception:  # noqa: BLE001
            pass

    # Update global state so the `/status` endpoint can instantly see both fields
    with _current_lock:
        global _current_frame_total  # noqa: PLW0603
        _current_frame_total = total_frames

    cmd = _build_cmd(mf, tmp_path, streams)
    log.debug("ffmpeg cmd: %s", " ".join(cmd))

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
        universal_newlines=True,
    )

    frames_done = 0
    # process.stdout is a text stream when universal_newlines=True
    for line in process.stdout:
        line = line.strip()
        if line.startswith("frame="):
            try:
                frames_done = int(line.split("=", 1)[1])
            except ValueError:
                pass
            
            with _current_lock:
                global _current_frame_now  # noqa: PLW0603
                _current_frame_now = frames_done
                
            if total_frames > 0:
                progress = min(99.0, (frames_done * 100.0) / total_frames)
            else:
                progress = 0.0  # Cannot compute percent, wait for total_frames
            db.update_progress(mf.uuid, progress)

    process.wait()
    if process.returncode != 0:
        stderr_out = ""
        if process.stderr:
            out_bytes = process.stderr.read()
            if out_bytes:
                stderr_out = out_bytes.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(
            f"ffmpeg exited {process.returncode}: {stderr_out[-600:]}"
        )


def _process_file(mf: MediaFile) -> None:
    tmp_path = os.path.join(WORKDIR, f"{mf.uuid}.mkv")
    dest_dir = os.path.dirname(mf.dest_path)

    # ── Pre-flight: probe streams and decide whether to skip ────────────────
    streams = _probe_streams(mf.source_path)
    if not streams:
        db.update_error(mf.uuid, "ffprobe returned no streams")
        return

    try:
        probe = ffmpeg.probe(mf.source_path)
    except ffmpeg.Error as exc:
        db.update_error(mf.uuid, f"ffprobe failed: {exc}")
        return

    skip, reason = _should_skip(mf, streams, probe)
    if skip:
        db.update_status(mf.uuid, FileStatus.ALREADY_OPTIMAL, 100.0)
        log.info(
            "Skipping %s (%s): %s",
            mf.clean_title,
            mf.year_or_episode,
            reason,
        )
        return

    # ── Encode ───────────────────────────────────────────────────────────────
    db.update_status(mf.uuid, FileStatus.IN_PROGRESS, 0.0)
    mf.status = FileStatus.IN_PROGRESS
    _write_progress_json(mf)
    _set_current(mf)
    log.info("Encoding: %s → %s", mf.source_path, mf.dest_path)

    try:
        _encode(mf, streams=streams)

        # Move to final destination
        os.makedirs(dest_dir, exist_ok=True)
        shutil.move(tmp_path, mf.dest_path)

        db.update_status(mf.uuid, FileStatus.DONE, 100.0)
        _append_flat_file(mf.file_hash)
        _remove_progress_json(mf.uuid)
        log.info("Done: %s", mf.dest_path)

        # Delete original source to reclaim space
        try:
            os.remove(mf.source_path)
            log.info("Deleted source file: %s", mf.source_path)
        except OSError as exc:
            log.warning("Could not delete source file %s: %s", mf.source_path, exc)

    except Exception as exc:  # noqa: BLE001
        _cleanup_workdir(mf.uuid)
        error_msg = str(exc)
        fresh = db.get_by_uuid(mf.uuid)
        error_count = fresh.error_count if fresh else 0
        if error_count < 1:
            # First failure — bump error count, requeue
            db.update_error(mf.uuid, error_msg)
            db.update_status(mf.uuid, FileStatus.PENDING, 0.0)
            log.warning("Encode failed (will retry once): %s — %s", mf.clean_title, error_msg)
        else:
            # Second failure — permanent error
            db.update_error(mf.uuid, error_msg)
            log.error("Encode failed permanently: %s — %s", mf.clean_title, error_msg)

        _remove_progress_json(mf.uuid)

    finally:
        _set_current(None, 0)


def _on_startup_cleanup() -> None:
    """Clean up any leftover workdir temp files from a previous crash."""
    # Ensure the workdir is accessible and writable
    try:
        os.makedirs(WORKDIR, exist_ok=True)
    except OSError as exc:
        log.error("Cannot create workdir %s: %s — encodes will fail", WORKDIR, exc)

    if not os.access(WORKDIR, os.W_OK):
        log.error(
            "Workdir %s is not writable. "
            "Check volume mount permissions (run.sh: --userns=keep-id).",
            WORKDIR,
        )

    # Remove leftover temp files from a previous crash
    try:
        for fname in os.listdir(WORKDIR):
            if fname.endswith(".mkv"):
                path = os.path.join(WORKDIR, fname)
                log.warning("Removing leftover temp file: %s", path)
                os.remove(path)
    except OSError:
        pass
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
