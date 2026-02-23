"""
transcoder.py — On-demand transcoder worker for SpaceSaver.

Responsibilities:
  - A single worker thread watches for QUEUED items
  - Picks up the next QUEUED file, sets IN_PROGRESS, encodes it
  - Status transitions: QUEUED → IN_PROGRESS → DONE / OPTIMUM
  - Writes temp file to /workdir/<uuid>.mkv, moves to /dest/... on success
  - Progress tracked in the `progress` table

No auto-start loop — transcoding is triggered by the enqueue endpoints
setting a file's status to QUEUED.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from typing import Dict, Optional, Tuple

import ffmpeg

import db
from config import cfg
from models import Entry, FileStatus

log = logging.getLogger(__name__)

WORKDIR = "/workdir"

# Audio codecs considered lossless / uncompressed → need re-encoding
_LOSSLESS_CODECS = {
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_s16be",
    "pcm_s24be", "pcm_s32be", "pcm_f64le", "pcm_f64be",
    "truehd", "mlp", "flac",
}

# Source video codecs that are already HEVC — re-encoding would lose quality
_HEVC_CODECS = {"hevc", "h265"}

# Conservative CRF → max expected bitrate (kbps) at 1080p for libx265.
_CRF_BITRATE_TABLE = {
    16: 8000,
    18: 5500,
    20: 3800,
    22: 2500,
    24: 1700,
    26: 1200,
    28:  800,
}
_CRF_BITRATE_DEFAULT = 5500
_PIXELS_1080P = 1920 * 1080

_stop_event = threading.Event()
_conn: Optional[sqlite3.Connection] = None

# Current file tracking for /status endpoint
_current_entry: Optional[Entry] = None
_current_progress: Optional[Dict] = None
_current_lock = threading.Lock()


def get_current_info() -> Optional[dict]:
    """Return current file info for the /status endpoint."""
    with _current_lock:
        if _current_entry is None:
            return None
        return {
            "uuid": _current_entry.uuid,
            "name": _current_entry.name,
            "frame_current": (_current_progress or {}).get("frame_current", 0),
            "frame_total": (_current_progress or {}).get("frame_total", 0),
            "progress": (_current_progress or {}).get("progress", 0.0),
        }


def _set_current(entry: Optional[Entry], progress_info: Optional[Dict] = None) -> None:
    global _current_entry, _current_progress  # noqa: PLW0603
    with _current_lock:
        _current_entry = entry
        _current_progress = progress_info or {}


# ── ffprobe helpers ──────────────────────────────────────────────────────────

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
    name = codec_name.lower()
    prof = (profile or "").lower()
    if name != "dts":
        return False
    return "ma" in prof or "hd" in prof or "x" in prof


def _effective_crf(entry: Entry) -> int:
    """Determine CRF — for now uses global config (per-file overrides removed)."""
    # TODO: re-add per-file overrides when quality config endpoints return
    return cfg.movie_crf


def _effective_res_cap(entry: Entry) -> int:
    """Determine resolution cap — for now uses global config."""
    return cfg.movie_res_cap


def _crf_bitrate_threshold(crf: int) -> int:
    if crf in _CRF_BITRATE_TABLE:
        return _CRF_BITRATE_TABLE[crf]
    lower = max((k for k in _CRF_BITRATE_TABLE if k <= crf), default=None)
    upper = min((k for k in _CRF_BITRATE_TABLE if k >= crf), default=None)
    if lower is None:
        return _CRF_BITRATE_TABLE[min(_CRF_BITRATE_TABLE)]
    if upper is None:
        return _CRF_BITRATE_TABLE[max(_CRF_BITRATE_TABLE)]
    lo_bps, hi_bps = _CRF_BITRATE_TABLE[lower], _CRF_BITRATE_TABLE[upper]
    ratio = (crf - lower) / (upper - lower)
    return int(lo_bps + ratio * (hi_bps - lo_bps))


# ── Skip detection ───────────────────────────────────────────────────────────

def _should_skip(entry: Entry, streams: list, probe: dict) -> Tuple[bool, str]:
    """
    Decide whether encoding this file would be wasteful.
    Returns (skip: bool, reason: str).
    """
    video_streams = [s for s in streams if s.get("codec_type") == "video"]

    # 0. Source exceeds resolution cap → must transcode to downscale
    res_cap = _effective_res_cap(entry)
    if res_cap > 0:
        max_height = max((s.get("height", 0) for s in video_streams), default=0)
        if max_height > res_cap:
            return False, ""

    # 1. Source is already HEVC
    for vs in video_streams:
        codec = vs.get("codec_name", "").lower()
        if codec in _HEVC_CODECS:
            return True, "source is already HEVC/H.265"

    # 2. Source bitrate already below CRF threshold
    try:
        source_kbps = int(probe.get("format", {}).get("bit_rate", 0)) // 1000
    except (TypeError, ValueError):
        source_kbps = 0

    if source_kbps > 0:
        max_pixels = max(
            (vs.get("width", 1920) * vs.get("height", 1080) for vs in video_streams),
            default=_PIXELS_1080P,
        )
        normalised_kbps = int(source_kbps * _PIXELS_1080P / max(max_pixels, 1))
        crf = _effective_crf(entry)
        threshold = _crf_bitrate_threshold(crf)
        if normalised_kbps < threshold:
            return (
                True,
                f"source bitrate {source_kbps} kbps (≈{normalised_kbps} kbps @1080p) "
                f"already below CRF {crf} threshold {threshold} kbps",
            )

    return False, ""


# ── ffmpeg command builder ───────────────────────────────────────────────────

def _build_cmd(entry: Entry, tmp_path: str, streams: list) -> list:
    crf = _effective_crf(entry)
    res_cap = _effective_res_cap(entry)

    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    video_streams = [s for s in streams if s.get("codec_type") == "video"]

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", entry.path,
        "-map", "0:v?",
        "-map", "0:a?",
        "-map", "0:s?",
        "-c:v", "libx265",
        "-crf", str(crf),
        "-preset", "slow",
        "-x265-params", "log-level=error",
    ]

    # Video scaling
    max_height = max((s.get("height", 0) for s in video_streams), default=0)
    if res_cap > 0 and max_height > res_cap:
        cmd += ["-vf", f"scale=-2:{res_cap}"]

    # Audio: per-stream codec selection
    any_lossless = any(
        _is_lossless(s.get("codec_name", "")) or
        _is_dts_hd(s.get("codec_name", ""), s.get("profile", ""))
        for s in audio_streams
    )

    if not any_lossless:
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

    cmd += ["-c:s", "copy"]
    cmd += ["-progress", "pipe:1", "-nostats"]
    cmd += ["-f", "matroska", tmp_path]

    return cmd


# ── Encoding ─────────────────────────────────────────────────────────────────

def _encode(conn: sqlite3.Connection, entry: Entry, streams: list) -> None:
    """Run ffmpeg as a subprocess, updating progress in the DB from stdout."""
    tmp_path = os.path.join(WORKDIR, f"{entry.uuid}.mkv")

    # Estimate total frames
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

    # Fallback: container duration
    if total_frames == 0:
        try:
            probe = ffmpeg.probe(entry.path)
            dur = float(probe.get("format", {}).get("duration", 0) or 0)
            total_frames = int(dur * 25)
        except Exception:  # noqa: BLE001
            pass

    # Update progress with total frames
    db.update_progress(conn, entry.uuid, frame_total=total_frames)
    _set_current(entry, {"frame_current": 0, "frame_total": total_frames, "progress": 0.0})

    cmd = _build_cmd(entry, tmp_path, streams)
    log.debug("ffmpeg cmd: %s", " ".join(cmd))

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
        universal_newlines=True,
    )

    frames_done = 0
    last_logged_progress = -5.0
    last_logged_time = time.time()

    for line in process.stdout:
        line = line.strip()
        if line.startswith("frame="):
            try:
                frames_done = int(line.split("=", 1)[1])
            except ValueError:
                pass

            if total_frames > 0:
                progress = min(99.0, (frames_done * 100.0) / total_frames)
            else:
                progress = 0.0

            db.update_progress(
                conn, entry.uuid,
                progress=progress,
                frame_current=frames_done,
            )

            with _current_lock:
                if _current_progress is not None:
                    _current_progress["frame_current"] = frames_done
                    _current_progress["progress"] = progress

            # <telemetry>: transcode_progress(uuid=<uuid>, progress=<pct>, frame=<n>/<total>)
            now = time.time()
            if progress - last_logged_progress >= 5.0 or (now - last_logged_time) >= 3600:
                log.info(
                    "[transcode_flow] event=transcode_progress uuid=%s progress=%.1f frames=%d/%d",
                    entry.uuid, progress, frames_done, total_frames,
                )
                last_logged_progress = progress
                last_logged_time = now

    process.wait()
    if process.returncode != 0:
        stderr_out = ""
        if process.stderr:
            out_bytes = process.stderr.read()
            if out_bytes:
                stderr_out = out_bytes if isinstance(out_bytes, str) else out_bytes.decode("utf-8", errors="ignore")
                stderr_out = stderr_out.strip()
        raise RuntimeError(
            f"ffmpeg exited {process.returncode}: {stderr_out[-600:]}"
        )


# ── File processing ──────────────────────────────────────────────────────────

def _dest_path_for(entry: Entry) -> str:
    """Build a destination path in the same directory as the source."""
    src_dir = os.path.dirname(entry.path)
    filename = f"{entry.hash}.{entry.name}.mkv"
    return os.path.join(src_dir, filename)


def _cleanup_workdir(uuid: str) -> None:
    tmp = os.path.join(WORKDIR, f"{uuid}.mkv")
    try:
        os.remove(tmp)
    except FileNotFoundError:
        pass


def _process_file(conn: sqlite3.Connection, entry: Entry) -> None:
    """Process a single QUEUED file through the transcode pipeline."""
    tmp_path = os.path.join(WORKDIR, f"{entry.uuid}.mkv")
    dest_path = _dest_path_for(entry)
    dest_dir = os.path.dirname(dest_path)

    # <telemetry>: transcode_started(uuid=<uuid>) — beginning transcode
    log.info("[transcode_flow] event=transcode_started uuid=%s path=%s", entry.uuid, entry.path)

    # ── Pre-flight: probe streams and decide whether to skip ────────────────
    streams = _probe_streams(entry.path)
    if not streams:
        log.error("[transcode_flow] event=transcode_failed uuid=%s reason=no_streams", entry.uuid)
        db.update_progress(conn, entry.uuid, status=FileStatus.PENDING)
        return

    try:
        probe = ffmpeg.probe(entry.path)
    except ffmpeg.Error as exc:
        log.error("[transcode_flow] event=transcode_failed uuid=%s reason=probe_error error=%s", entry.uuid, exc)
        db.update_progress(conn, entry.uuid, status=FileStatus.PENDING)
        return

    skip, reason = _should_skip(entry, streams, probe)
    if skip:
        db.update_progress(conn, entry.uuid, status=FileStatus.OPTIMUM, progress=100.0)
        # <telemetry>: transcode_skipped(uuid=<uuid>, reason=<reason>)
        log.info("[transcode_flow] event=transcode_skipped uuid=%s reason=%s", entry.uuid, reason)
        return

    # ── Encode ───────────────────────────────────────────────────────────────
    db.update_progress(
        conn, entry.uuid,
        status=FileStatus.IN_PROGRESS,
        progress=0.0,
        workfile=tmp_path,
    )
    _set_current(entry, {"frame_current": 0, "frame_total": 0, "progress": 0.0})

    try:
        _encode(conn, entry, streams=streams)

        # Move to final destination
        os.makedirs(dest_dir, exist_ok=True)
        shutil.move(tmp_path, dest_path)

        db.update_progress(conn, entry.uuid, status=FileStatus.DONE, progress=100.0, workfile=None)

        # <telemetry>: transcode_completed(uuid=<uuid>) — transcode finished
        log.info("[transcode_flow] event=transcode_completed uuid=%s dest=%s", entry.uuid, dest_path)

        # Delete original source to reclaim space
        try:
            os.remove(entry.path)
            log.info("[transcode_flow] event=source_deleted path=%s", entry.path)
        except OSError as exc:
            log.warning("[transcode_flow] event=source_delete_failed path=%s error=%s", entry.path, exc)

    except Exception as exc:  # noqa: BLE001
        _cleanup_workdir(entry.uuid)
        # <telemetry>: transcode_failed(uuid=<uuid>, error=<msg>)
        error_msg = str(exc)
        log.error("[transcode_flow] event=transcode_failed uuid=%s error=%s", entry.uuid, error_msg)
        db.update_progress(conn, entry.uuid, status=FileStatus.PENDING, progress=0.0, workfile=None)

    finally:
        _set_current(None)


# ── Worker loop ──────────────────────────────────────────────────────────────

def _on_startup_cleanup() -> None:
    """Clean up leftover workdir temp files from a previous crash."""
    try:
        os.makedirs(WORKDIR, exist_ok=True)
    except OSError as exc:
        log.error("Cannot create workdir %s: %s — encodes will fail", WORKDIR, exc)

    if not os.access(WORKDIR, os.W_OK):
        log.error("Workdir %s is not writable.", WORKDIR)

    try:
        for fname in os.listdir(WORKDIR):
            if fname.endswith(".mkv"):
                path = os.path.join(WORKDIR, fname)
                log.warning("Removing leftover temp file: %s", path)
                os.remove(path)
    except OSError:
        pass


def _pick_next_queued(conn: sqlite3.Connection) -> Optional[Entry]:
    """Pick the next QUEUED entry (by insertion order)."""
    cur = conn.execute(
        """SELECT e.* FROM entries e
           JOIN progress p ON e.uuid = p.uuid
           WHERE p.status = ?
           ORDER BY e.rowid ASC
           LIMIT 1""",
        (FileStatus.QUEUED.value,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return Entry(uuid=row["uuid"], name=row["name"], hash=row["hash"],
                 path=row["path"], size=row["size"])


def run(conn: sqlite3.Connection) -> None:
    """Entry point for the transcoder worker thread."""
    _on_startup_cleanup()
    log.info("Transcoder worker started. Workdir: %s", WORKDIR)
    while not _stop_event.is_set():
        entry = _pick_next_queued(conn)
        if entry is None:
            # <telemetry>: alive(file=None, progress=0, cpu=..., mem=...) — idle heartbeat
            _stop_event.wait(5)
            continue
        try:
            _process_file(conn, entry)
        except Exception as exc:  # noqa: BLE001
            log.exception("[transcode_flow] event=unexpected_error error=%s", exc)
            _stop_event.wait(5)
    # <telemetry>: service_stop — transcoder worker shutting down
    log.info("Transcoder worker stopped.")


def start(conn: sqlite3.Connection) -> threading.Thread:
    global _conn  # noqa: PLW0603
    _conn = conn
    t = threading.Thread(target=run, args=(conn,), name="transcoder", daemon=True)
    t.start()
    return t


def stop() -> None:
    _stop_event.set()
