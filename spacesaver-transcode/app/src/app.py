"""
app.py — Flask routing and lifecycle for SpaceSaver.

Thin layer: routes delegate to controllers, startup initialises DB/scanner/transcoder.
"""

from __future__ import annotations

import logging
import os
import threading

from flask import Flask, jsonify

import controllers
import db
import scanner
import transcoder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

_started = False
_startup_lock = threading.Lock()
_conn = None

MEDIA_DIRS = ["/media"]


def _ensure_started() -> None:
    global _started, _conn  # noqa: PLW0603
    if _started:
        return
    with _startup_lock:
        if _started:
            return
        _started = True
        _conn = db.init_db()
        result = scanner.scan_sources(MEDIA_DIRS, _conn)
        log.info("Startup scan: added=%d skipped=%d errors=%d", result.added, result.skipped, result.errors)
        transcoder.start(_conn)
        log.info("SpaceSaver started.")


@app.before_request
def _startup():
    _ensure_started()


# ── Routes (thin wrappers around controllers) ───────────────────────────────

@app.get("/version")
def version():
    body, code = controllers.get_version()
    return jsonify(body), code

@app.get("/list")
def list_all():
    body, code = controllers.list_all(_conn)
    return jsonify(body), code

@app.get("/list/<uuid>")
def list_one(uuid: str):
    body, code = controllers.list_one(_conn, uuid)
    return jsonify(body), code

@app.get("/status")
def status():
    body, code = controllers.get_status(_conn)
    return jsonify(body), code

@app.post("/request/enqueue/<uuid>")
def enqueue_uuid(uuid: str):
    body, code = controllers.enqueue_uuid(_conn, uuid)
    return jsonify(body), code

@app.post("/request/enqueue/best")
def enqueue_best():
    body, code = controllers.enqueue_best(_conn)
    return jsonify(body), code


# ── Entrypoint ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
