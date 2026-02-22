"""
controllers.py — Pure request handlers for SpaceSaver.

Each function takes a DB connection (and any route params) and returns
(response_dict, http_status_code).  No Flask imports — testable without
a running app.
"""

from __future__ import annotations

import logging
import pathlib
import sqlite3
from typing import Tuple

import db
import transcoder
from models import FileStatus, MetadataKind

log = logging.getLogger(__name__)

_VERSION_FILE = pathlib.Path(__file__).parent.parent / "version.txt"


def _read_version() -> str:
    try:
        return _VERSION_FILE.read_text().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


# ── GET /version ─────────────────────────────────────────────────────────────

def get_version() -> Tuple[dict, int]:
    return {"version": _read_version()}, 200


# ── GET /list ────────────────────────────────────────────────────────────────

def list_all(conn: sqlite3.Connection) -> Tuple[list, int]:
    entries = db.list_entries(conn)
    items = []
    for entry in entries:
        progress = db.get_progress(conn, entry.uuid)
        meta = db.get_metadata(conn, entry.uuid, MetadataKind.DECLARED)
        items.append({
            "uuid": entry.uuid,
            "name": entry.name,
            "size": entry.size,
            "status": progress.status.value if progress else "unknown",
            "progress": progress.progress if progress else 0.0,
            "codec": meta.codec if meta else "Unknown",
        })
    return items, 200


# ── GET /list/<uuid> ─────────────────────────────────────────────────────────

def list_one(conn: sqlite3.Connection, uuid: str) -> Tuple[dict, int]:
    entry = db.get_entry_by_uuid(conn, uuid)
    if entry is None:
        return {"error": "not found"}, 404

    progress = db.get_progress(conn, uuid)
    metadata_rows = db.get_all_metadata(conn, uuid)

    result = entry.to_dict()
    result["progress"] = progress.to_dict() if progress else None
    result["metadata"] = [m.to_dict() for m in metadata_rows]
    return result, 200


# ── GET /status ──────────────────────────────────────────────────────────────

def get_status(conn: sqlite3.Connection) -> Tuple[dict, int]:
    counts = db.count_by_status(conn)
    current_info = transcoder.get_current_info()
    return {
        "total": sum(counts.values()),
        "pending": counts.get(FileStatus.PENDING.value, 0),
        "queued": counts.get(FileStatus.QUEUED.value, 0),
        "in_progress": counts.get(FileStatus.IN_PROGRESS.value, 0),
        "done": counts.get(FileStatus.DONE.value, 0),
        "optimum": counts.get(FileStatus.OPTIMUM.value, 0),
        "current_file": current_info,
    }, 200


# ── POST /request/enqueue/<uuid> ────────────────────────────────────────────

def enqueue_uuid(conn: sqlite3.Connection, uuid: str) -> Tuple[dict, int]:
    log.info("[enqueue] event=requested uuid=%s", uuid)

    entry = db.get_entry_by_uuid(conn, uuid)
    if entry is None:
        log.info("[enqueue] event=rejected uuid=%s reason=not_found", uuid)
        return {"error": "not found"}, 404

    progress = db.get_progress(conn, uuid)
    if progress is not None and progress.status in (FileStatus.QUEUED, FileStatus.IN_PROGRESS):
        log.info("[enqueue] event=rejected uuid=%s reason=already_%s", uuid, progress.status.value)
        return {"error": f"already {progress.status.value}"}, 409

    db.set_status(conn, uuid, FileStatus.QUEUED)
    log.info("[enqueue] event=accepted uuid=%s", uuid)
    return {"uuid": uuid, "status": "queued"}, 202


# ── POST /request/enqueue/best ──────────────────────────────────────────────

def enqueue_best(conn: sqlite3.Connection) -> Tuple[dict, int]:
    log.info("[enqueue_best] event=requested")

    if db.has_active_queue(conn):
        log.info("[enqueue_best] event=conflict")
        return {"error": "queue already active"}, 409

    best = db.query_best_candidate(conn)
    if best is None:
        log.info("[enqueue_best] event=no_candidate")
        return {"error": "no eligible candidates"}, 404

    db.set_status(conn, best.uuid, FileStatus.QUEUED)
    log.info("[enqueue_best] event=selected uuid=%s size=%d", best.uuid, best.size)
    return {"uuid": best.uuid, "name": best.name, "size": best.size}, 202
