"""
app.py — Flask application and HTTP API entry point for SpaceSaver.

Endpoints (all cluster-internal, no auth):
  GET  /list                     — all files (summary)
  GET  /list/<uuid>              — single file (full detail)
  GET  /status                   — queue summary, current file, ETA
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
_start_time = time.time()


def _ensure_started() -> None:
    global _started  # noqa: PLW0603
    if not _started:
        _started = True
        db.init_db()
        scanner.start()
        transcoder.start()
        log.info("SpaceSaver started. Uptime clock running.")


@app.before_request
def _startup():
    _ensure_started()


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

    current = transcoder.get_current_file()
    current_info = None
    eta_seconds = None

    if current is not None:
        progress = current.progress
        current_info = {
            "uuid": current.uuid,
            "name": f"{current.clean_title} {current.year_or_episode}".strip(),
            "progress": round(progress, 1),
        }
        # Crude ETA: assume linear progress from when file started
        # We don't track per-file start time here, so we use a simple estimate
        if progress > 1.0:
            uptime = time.time() - _start_time
            rate = progress / max(uptime, 1)
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
            "current_file": current_info,
            "eta_seconds": eta_seconds,
        }
    )


# ─── /config/quality ─────────────────────────────────────────────────────────

@app.get("/config/quality")
def get_quality():
    return jsonify(cfg.to_dict())


@app.post("/config/quality")
def set_quality():
    data = request.get_json(silent=True) or {}
    cfg.update(data)
    return jsonify({"ok": True, "config": cfg.to_dict()})


@app.post("/config/quality/<uuid>")
def set_quality_for_file(uuid: str):
    mf = db.get_by_uuid(uuid)
    if mf is None:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(silent=True) or {}
    allowed = {"tv_crf", "movie_crf", "tv_res_cap", "movie_res_cap"}
    overrides = {k: v for k, v in data.items() if k in allowed}
    db.update_quality_override(uuid, overrides)

    # Requeue if already DONE so it gets re-encoded
    if mf.status == FileStatus.DONE:
        db.update_status(uuid, FileStatus.PENDING, 0.0)
        log.info("Requeued %s for re-encode with new quality settings", uuid)

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
