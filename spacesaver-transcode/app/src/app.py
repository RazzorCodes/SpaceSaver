"""
app.py — Flask application and HTTP API entry point for SpaceSaver.

Database-first, on-demand architecture:
  - On startup: validate schema → scan sources once → ready
  - No auto-transcoder — files are processed only when explicitly enqueued

Endpoints (all cluster-internal, no auth):
  GET  /list                        — all files (summary)
  GET  /list/<uuid>                 — single file (full detail)
  GET  /status                      — queue summary
  GET  /version                     — image version string
  POST /request/enqueue/<uuid>      — enqueue a specific file
  POST /request/enqueue/best        — auto-select and enqueue the best candidate
"""

from __future__ import annotations

import logging
import os
import pathlib
import threading

from flask import Flask, jsonify

import db
import scanner
import transcoder
from models import FileStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# <telemetry>: service_start — SpaceSaver transcoder starting up

app = Flask(__name__)

_started = False
_startup_lock = threading.Lock()
_conn = None  # module-level DB connection, set during startup
_VERSION_FILE = pathlib.Path(__file__).parent.parent / "version.txt"

SOURCE_DIRS = ["/source"]  # configurable list of source directories


def _read_version() -> str:
    try:
        return _VERSION_FILE.read_text().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _ensure_started() -> None:
    global _started, _conn  # noqa: PLW0603
    if not _started:
        with _startup_lock:
            if not _started:
                _started = True

                # 1. Init DB (validate schema, drop-recreate if mismatch)
                _conn = db.init_db()

                # 2. Scan sources once (do not auto-start processing)
                result = scanner.scan_sources(SOURCE_DIRS, _conn)
                log.info(
                    "Startup scan complete: added=%d skipped=%d errors=%d",
                    result.added, result.skipped, result.errors,
                )

                # 3. Start the transcoder worker thread (picks up QUEUED items)
                transcoder.start(_conn)

                log.info("SpaceSaver started (on-demand mode).")


def _get_conn():
    """Get the module-level DB connection (initialised during startup)."""
    return _conn


@app.before_request
def _startup():
    _ensure_started()


# ─── /version ───────────────────────────────────────────────────────────────

@app.get("/version")
def version():
    return jsonify({"version": _read_version()})


# ─── /list ──────────────────────────────────────────────────────────────────

@app.get("/list")
def list_all():
    conn = _get_conn()
    entries = db.list_entries(conn)
    items = []
    for entry in entries:
        progress = db.get_progress(conn, entry.uuid)
        meta = db.get_metadata(conn, entry.uuid, db.MetadataKind.DECLARED)
        items.append({
            "uuid": entry.uuid,
            "name": entry.name,
            "size": entry.size,
            "status": progress.status.value if progress else "unknown",
            "progress": progress.progress if progress else 0.0,
            "codec": meta.codec if meta else "Unknown",
        })
    return jsonify(items)


@app.get("/list/<uuid>")
def list_one(uuid: str):
    conn = _get_conn()
    entry = db.get_entry_by_uuid(conn, uuid)
    if entry is None:
        return jsonify({"error": "not found"}), 404

    progress = db.get_progress(conn, uuid)
    metadata_rows = db.get_all_metadata(conn, uuid)

    result = entry.to_dict()
    result["progress"] = progress.to_dict() if progress else None
    result["metadata"] = [m.to_dict() for m in metadata_rows]
    return jsonify(result)


# ─── /status ────────────────────────────────────────────────────────────────

@app.get("/status")
def status():
    conn = _get_conn()
    counts = db.count_by_status(conn)
    total = sum(counts.values())
    pending = counts.get(FileStatus.PENDING.value, 0)
    queued = counts.get(FileStatus.QUEUED.value, 0)
    in_progress = counts.get(FileStatus.IN_PROGRESS.value, 0)
    done = counts.get(FileStatus.DONE.value, 0)
    optimum = counts.get(FileStatus.OPTIMUM.value, 0)

    current_info = transcoder.get_current_info()

    return jsonify({
        "total": total,
        "pending": pending,
        "queued": queued,
        "in_progress": in_progress,
        "done": done,
        "optimum": optimum,
        "current_file": current_info,
    })


# ─── /request/enqueue ──────────────────────────────────────────────────────

@app.post("/request/enqueue/<uuid>")
def enqueue_uuid(uuid: str):
    """
    Enqueue a specific file for transcoding.

    Flow:
      1. Look up uuid in entries — 404 if not found
      2. Check progress.status — reject 409 if already QUEUED or IN_PROGRESS
      3. Set status → QUEUED
      4. Return 202 Accepted
    """
    conn = _get_conn()

    # <telemetry>: enqueue_requested(uuid=<uuid>) — enqueue request received
    log.info("[enqueue_flow] event=enqueue_requested uuid=%s", uuid)

    # 1. Look up entry
    entry = db.get_entry_by_uuid(conn, uuid)
    if entry is None:
        # <telemetry>: enqueue_rejected(reason=not_found)
        log.info("[enqueue_flow] event=enqueue_rejected uuid=%s reason=not_found", uuid)
        return jsonify({"error": "not found"}), 404

    # 2. Check current status
    progress = db.get_progress(conn, uuid)
    if progress is not None and progress.status in (FileStatus.QUEUED, FileStatus.IN_PROGRESS):
        # <telemetry>: enqueue_rejected(reason=already_active)
        log.info(
            "[enqueue_flow] event=enqueue_rejected uuid=%s reason=already_%s",
            uuid, progress.status.value,
        )
        return jsonify({"error": f"already {progress.status.value}"}), 409

    # 3. Set status → QUEUED
    db.set_status(conn, uuid, FileStatus.QUEUED)

    # <telemetry>: enqueue_accepted — file queued for transcoding
    log.info("[enqueue_flow] event=enqueue_accepted uuid=%s", uuid)

    return jsonify({"uuid": uuid, "status": "queued"}), 202


@app.post("/request/enqueue/best")
def enqueue_best():
    """
    Select and enqueue the best candidate automatically.

    Selection: PENDING files ordered by size DESC, take first.
    Rejects with 409 if queue already has QUEUED/IN_PROGRESS item.
    Returns 404 if no eligible candidates.
    """
    conn = _get_conn()

    # <telemetry>: enqueue_best_requested — best-candidate enqueue request received
    log.info("[enqueue_best_flow] event=enqueue_best_requested")

    # Check if queue already has an active item
    if db.has_active_queue(conn):
        # <telemetry>: enqueue_best_conflict — queue already has active item
        log.info("[enqueue_best_flow] event=enqueue_best_conflict")
        return jsonify({"error": "queue already active"}), 409

    # Find best candidate
    best = db.query_best_candidate(conn)
    if best is None:
        # <telemetry>: enqueue_best_no_candidate — no eligible PENDING files
        log.info("[enqueue_best_flow] event=enqueue_best_no_candidate")
        return jsonify({"error": "no eligible candidates"}), 404

    # Enqueue it
    db.set_status(conn, best.uuid, FileStatus.QUEUED)

    # <telemetry>: enqueue_best_selected(uuid=<uuid>, size=<size>) — candidate selected
    log.info(
        "[enqueue_best_flow] event=enqueue_best_selected uuid=%s size=%d",
        best.uuid, best.size,
    )

    return jsonify({"uuid": best.uuid, "name": best.name, "size": best.size}), 202


# ─── Entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
    # <telemetry>: service_stop — SpaceSaver transcoder shutting down
