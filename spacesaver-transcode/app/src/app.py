"""
app.py — Flask application and HTTP API entry point for SpaceSaver.

Endpoints (all cluster-internal, no auth):
  GET  /list                     — all files (summary)
  GET  /list/<uuid>              — single file (full detail)
  GET  /status                   — queue summary, current file, ETA
  GET  /version                  — image version string
  GET  /config/quality           — current global quality settings
  POST /config/quality           — update global quality settings
  POST /config/quality/<uuid>    — per-file quality override (+ requeue if DONE)
  POST /control/reset/<uuid>     — clear error and requeue
  POST /control/skip/<uuid>      — permanently skip a file

The scanner and transcoder are started as daemon threads on first request
(via before_first_request / startup hook) so the pod passes readiness checks
before the first scan completes.
"""

from __future__ import annotations

import logging
import os
import pathlib
import threading
import time

from flask import Flask, jsonify, request

import db
import scanner
import transcoder
from config import cfg
from models import FileStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

_started = False
_startup_lock = threading.Lock()
_start_time = time.time()
_VERSION_FILE = pathlib.Path(__file__).parent.parent / "version.txt"


def _read_version() -> str:
    try:
        return _VERSION_FILE.read_text().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _ensure_started() -> None:
    global _started  # noqa: PLW0603
    if not _started:
        with _startup_lock:
            if not _started:
                _started = True
                db.init_db()
                scanner.start()
                transcoder.start()
                log.info("SpaceSaver started. Uptime clock running.")


@app.before_request
def _startup():
    _ensure_started()


# ─── /version ───────────────────────────────────────────────────────────────

@app.get("/version")
def version():
    return jsonify({"version": _read_version()})


# ─── /list ───────────────────────────────────────────────────────────────────

@app.get("/list")
def list_all():
    files = db.list_all()
    return jsonify([f.to_dict(full=False) for f in files])


@app.get("/list/<uuid>")
def list_one(uuid: str):
    mf = db.get_by_uuid(uuid)
    if mf is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(mf.to_dict(full=True))


# ─── /status ─────────────────────────────────────────────────────────────────

@app.get("/status")
def status():
    counts = db.count_by_status()
    total = sum(counts.values())
    done = counts.get(FileStatus.DONE.value, 0)
    pending = counts.get(FileStatus.PENDING.value, 0)
    in_progress = counts.get(FileStatus.IN_PROGRESS.value, 0)
    error = counts.get(FileStatus.ERROR.value, 0)
    skipped = counts.get(FileStatus.SKIPPED.value, 0)

    current, current_start, frame_now, frame_total = transcoder.get_current_info()
    current_info = None
    eta_seconds = None

    if current is not None:
        progress = current.progress
        current_info = {
            "uuid": current.uuid,
            "name": f"{current.clean_title} {current.year_or_episode}".strip(),
            "progress": {
                "frame": {
                    "now": frame_now,
                    "total": frame_total
                }
            },
        }
        # ETA based on file start time
        if frame_now > 100 and current_start > 0:
            elapsed = time.time() - current_start
            rate = progress / max(elapsed, 1.0)
            remaining = (100.0 - progress) / max(rate, 0.01)
            eta_seconds = int(remaining)

    return jsonify(
        {
            "total": total,
            "pending": pending,
            "in_progress": in_progress,
            "done": done,
            "error": error,
            "skipped": skipped,
            "already_optimal": counts.get(FileStatus.ALREADY_OPTIMAL.value, 0),
            "current_file": current_info,
            "eta_seconds": eta_seconds,
        }
    )


# ─── /current ────────────────────────────────────────────────────────────────

@app.get("/current")
def current():
    mf = transcoder.get_current_file()
    if mf is None:
        return "", 204
    return jsonify(mf.to_dict(full=True))


# ─── /config/quality ─────────────────────────────────────────────────────────

@app.get("/config/quality")
def get_quality():
    return jsonify(cfg.to_dict())


@app.post("/config/quality")
def set_quality():
    data = request.get_json(silent=True) or {}
    cfg.update(data)
    reset_count = db.reset_already_optimal()
    scanner.trigger_rescan()
    log.info(
        "Quality config updated. %d already-optimal file(s) requeued; rescan triggered.",
        reset_count,
    )
    return jsonify({"ok": True, "config": cfg.to_dict(), "requeued": reset_count})


@app.post("/config/quality/<uuid>")
def set_quality_for_file(uuid: str):
    mf = db.get_by_uuid(uuid)
    if mf is None:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(silent=True) or {}
    allowed = {"tv_crf", "movie_crf", "tv_res_cap", "movie_res_cap"}
    overrides = {k: v for k, v in data.items() if k in allowed}
    db.update_quality_override(uuid, overrides)

    # Requeue if DONE or ALREADY_OPTIMAL so it gets re-evaluated / re-encoded
    if mf.status == FileStatus.DONE:
        db.update_status(uuid, FileStatus.PENDING, 0.0)
        log.info("Requeued %s for re-encode with new quality settings", uuid)
    elif mf.status == FileStatus.ALREADY_OPTIMAL:
        db.reset_already_optimal(uuid)
        log.info("Requeued already-optimal file %s for re-evaluation", uuid)

    return jsonify({"ok": True})


# ─── /control ────────────────────────────────────────────────────────────────

@app.post("/control/reset/<uuid>")
def reset_file(uuid: str):
    ok = db.reset_file(uuid)
    if not ok:
        return jsonify({"error": "not found"}), 404
    log.info("Reset file %s to pending", uuid)
    return jsonify({"ok": True})


@app.post("/control/skip/<uuid>")
def skip_file(uuid: str):
    ok = db.skip_file(uuid)
    if not ok:
        return jsonify({"error": "not found"}), 404
    log.info("Skipped file %s", uuid)
    return jsonify({"ok": True})


# ─── Entrypoint ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # Threaded=True so the two background threads + Flask can all run concurrently.
    # For production you'd use gunicorn, but for a single-pod workload Flask dev
    # server with threading is fine and avoids an extra dependency.
    app.run(host="0.0.0.0", port=port, threaded=True)
