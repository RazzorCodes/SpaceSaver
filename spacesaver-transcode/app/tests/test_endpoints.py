"""Tests for enqueue endpoints in app.py."""

import sqlite3
from unittest.mock import patch, MagicMock

import db
from models import Entry, FileStatus, Metadata, MetadataKind, Progress


def _in_memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(db._SCHEMA_SQL)
    return conn


def _make_app(conn):
    """Create a test Flask app with mocked startup."""
    # Patch the startup so it doesn't try to scan real dirs
    with patch("app._ensure_started"):
        import app as app_module
        app_module._conn = conn
        app_module._started = True
        return app_module.app


def _insert_test_entry(conn, name="Test Movie", hash_="h1", size=1000, status=FileStatus.PENDING):
    """Helper to insert a test entry with progress."""
    e = Entry.new(name=name, hash=hash_, path=f"/source/{name}.mkv", size=size)
    meta = Metadata(uuid=e.uuid, kind=MetadataKind.DECLARED, codec="h264")
    db.insert_new_file(conn, e, meta)
    if status != FileStatus.PENDING:
        db.set_status(conn, e.uuid, status)
    return e


# ── POST /request/enqueue/<uuid> ────────────────────────────────────────────

def test_enqueue_uuid_success():
    conn = _in_memory_db()
    e = _insert_test_entry(conn)
    app = _make_app(conn)
    with app.test_client() as client:
        resp = client.post(f"/request/enqueue/{e.uuid}")
        assert resp.status_code == 202
        data = resp.get_json()
        assert data["uuid"] == e.uuid
        assert data["status"] == "queued"
    # Verify DB was updated
    p = db.get_progress(conn, e.uuid)
    assert p.status == FileStatus.QUEUED


def test_enqueue_uuid_not_found():
    conn = _in_memory_db()
    app = _make_app(conn)
    with app.test_client() as client:
        resp = client.post("/request/enqueue/nonexistent-uuid")
        assert resp.status_code == 404


def test_enqueue_uuid_already_queued():
    conn = _in_memory_db()
    e = _insert_test_entry(conn, status=FileStatus.QUEUED)
    app = _make_app(conn)
    with app.test_client() as client:
        resp = client.post(f"/request/enqueue/{e.uuid}")
        assert resp.status_code == 409


def test_enqueue_uuid_already_in_progress():
    conn = _in_memory_db()
    e = _insert_test_entry(conn, status=FileStatus.IN_PROGRESS)
    app = _make_app(conn)
    with app.test_client() as client:
        resp = client.post(f"/request/enqueue/{e.uuid}")
        assert resp.status_code == 409


def test_enqueue_uuid_done_can_requeue():
    conn = _in_memory_db()
    e = _insert_test_entry(conn, status=FileStatus.DONE)
    app = _make_app(conn)
    with app.test_client() as client:
        resp = client.post(f"/request/enqueue/{e.uuid}")
        assert resp.status_code == 202


# ── POST /request/enqueue/best ──────────────────────────────────────────────

def test_enqueue_best_success():
    conn = _in_memory_db()
    e1 = _insert_test_entry(conn, name="Small", hash_="h1", size=100)
    e2 = _insert_test_entry(conn, name="Big", hash_="h2", size=9000)
    app = _make_app(conn)
    with app.test_client() as client:
        resp = client.post("/request/enqueue/best")
        assert resp.status_code == 202
        data = resp.get_json()
        assert data["uuid"] == e2.uuid  # Biggest file
        assert data["size"] == 9000


def test_enqueue_best_conflict():
    conn = _in_memory_db()
    _insert_test_entry(conn, name="Queued", hash_="h1", size=100, status=FileStatus.QUEUED)
    _insert_test_entry(conn, name="Pending", hash_="h2", size=200)
    app = _make_app(conn)
    with app.test_client() as client:
        resp = client.post("/request/enqueue/best")
        assert resp.status_code == 409


def test_enqueue_best_no_candidates():
    conn = _in_memory_db()
    # Insert only DONE entries
    _insert_test_entry(conn, name="Done", hash_="h1", size=100, status=FileStatus.DONE)
    app = _make_app(conn)
    with app.test_client() as client:
        resp = client.post("/request/enqueue/best")
        assert resp.status_code == 404


def test_enqueue_best_empty_db():
    conn = _in_memory_db()
    app = _make_app(conn)
    with app.test_client() as client:
        resp = client.post("/request/enqueue/best")
        assert resp.status_code == 404
