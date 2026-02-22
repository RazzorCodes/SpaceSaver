"""Tests for db.py — schema validation, CRUD, and query helpers."""

import sqlite3

import db
from models import (
    Entry,
    FileStatus,
    Metadata,
    MetadataKind,
    Progress,
)


def _in_memory_db() -> sqlite3.Connection:
    """Create an in-memory SQLite DB with the expected schema."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(db._SCHEMA_SQL)
    return conn


# ── Schema validation ────────────────────────────────────────────────────────

def test_validate_schema_fresh_db():
    """Schema validation on a newly validated DB should return True."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    db.validate_schema(conn)  # Creates the schema
    assert db.validate_schema(conn) is True


def test_validate_schema_empty_db():
    """Schema validation on an empty DB should create schema and return False."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    result = db.validate_schema(conn)
    assert result is False
    # Tables should now exist
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row["name"] for row in cur.fetchall()}
    assert "entries" in tables
    assert "metadata" in tables
    assert "progress" in tables


def test_validate_schema_mismatch():
    """Schema validation with wrong schema should drop and recreate."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Create a wrong schema
    conn.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, wrong TEXT)")
    conn.commit()
    result = db.validate_schema(conn)
    assert result is False
    # New correct schema should be in place
    cur = conn.execute("PRAGMA table_info(entries)")
    cols = {row["name"] for row in cur.fetchall()}
    assert "uuid" in cols
    assert "wrong" not in cols


# ── Entry operations ─────────────────────────────────────────────────────────

def test_insert_and_get_entry():
    conn = _in_memory_db()
    e = Entry.new(name="Test Movie", hash="abc123", path="/source/test.mkv", size=1000)
    db.insert_entry(conn, e)
    result = db.get_entry_by_uuid(conn, e.uuid)
    assert result is not None
    assert result.name == "Test Movie"
    assert result.hash == "abc123"
    assert result.size == 1000


def test_get_entry_by_hash_and_path():
    conn = _in_memory_db()
    e = Entry.new(name="Movie", hash="xyz", path="/source/movie.mkv", size=500)
    db.insert_entry(conn, e)
    result = db.get_entry_by_hash_and_path(conn, "xyz", "/source/movie.mkv")
    assert result is not None
    assert result.uuid == e.uuid


def test_get_entry_not_found():
    conn = _in_memory_db()
    assert db.get_entry_by_uuid(conn, "nonexistent") is None


def test_list_entries():
    conn = _in_memory_db()
    e1 = Entry.new(name="Movie 1", hash="h1", path="/source/m1.mkv", size=100)
    e2 = Entry.new(name="Movie 2", hash="h2", path="/source/m2.mkv", size=200)
    db.insert_entry(conn, e1)
    db.insert_entry(conn, e2)
    entries = db.list_entries(conn)
    assert len(entries) == 2


# ── Metadata operations ─────────────────────────────────────────────────────

def test_insert_and_get_metadata():
    conn = _in_memory_db()
    e = Entry.new(name="Movie", hash="h1", path="/source/m.mkv", size=100)
    db.insert_entry(conn, e)
    meta = Metadata(uuid=e.uuid, kind=MetadataKind.DECLARED, codec="h264", resolution="1920x1080")
    db.insert_metadata(conn, meta)
    result = db.get_metadata(conn, e.uuid, MetadataKind.DECLARED)
    assert result is not None
    assert result.codec == "h264"
    assert result.resolution == "1920x1080"


def test_get_all_metadata():
    conn = _in_memory_db()
    e = Entry.new(name="Movie", hash="h1", path="/source/m.mkv", size=100)
    db.insert_entry(conn, e)
    m1 = Metadata(uuid=e.uuid, kind=MetadataKind.DECLARED, codec="h264")
    m2 = Metadata(uuid=e.uuid, kind=MetadataKind.ACTUAL, codec="h265")
    db.insert_metadata(conn, m1)
    db.insert_metadata(conn, m2)
    all_meta = db.get_all_metadata(conn, e.uuid)
    assert len(all_meta) == 2


# ── Progress operations ─────────────────────────────────────────────────────

def test_insert_and_get_progress():
    conn = _in_memory_db()
    e = Entry.new(name="Movie", hash="h1", path="/source/m.mkv", size=100)
    db.insert_entry(conn, e)
    p = Progress(uuid=e.uuid)
    db.insert_progress(conn, p)
    result = db.get_progress(conn, e.uuid)
    assert result is not None
    assert result.status == FileStatus.PENDING
    assert result.progress == 0.0


def test_set_status():
    conn = _in_memory_db()
    e = Entry.new(name="Movie", hash="h1", path="/source/m.mkv", size=100)
    db.insert_entry(conn, e)
    db.insert_progress(conn, Progress(uuid=e.uuid))
    db.set_status(conn, e.uuid, FileStatus.QUEUED)
    result = db.get_progress(conn, e.uuid)
    assert result.status == FileStatus.QUEUED


def test_update_progress_fields():
    conn = _in_memory_db()
    e = Entry.new(name="Movie", hash="h1", path="/source/m.mkv", size=100)
    db.insert_entry(conn, e)
    db.insert_progress(conn, Progress(uuid=e.uuid))
    db.update_progress(conn, e.uuid, progress=50.0, frame_current=500, frame_total=1000)
    result = db.get_progress(conn, e.uuid)
    assert result.progress == 50.0
    assert result.frame_current == 500
    assert result.frame_total == 1000


# ── Query helpers ────────────────────────────────────────────────────────────

def test_query_best_candidate():
    conn = _in_memory_db()
    # Insert 3 entries with different sizes
    for name, hash_, size in [("Small", "h1", 100), ("Big", "h2", 9000), ("Medium", "h3", 500)]:
        e = Entry.new(name=name, hash=hash_, path=f"/source/{name}.mkv", size=size)
        db.insert_entry(conn, e)
        db.insert_progress(conn, Progress(uuid=e.uuid, status=FileStatus.PENDING))

    best = db.query_best_candidate(conn)
    assert best is not None
    assert best.name == "Big"
    assert best.size == 9000


def test_query_best_candidate_skips_non_pending():
    conn = _in_memory_db()
    e1 = Entry.new(name="Done", hash="h1", path="/source/d.mkv", size=9000)
    e2 = Entry.new(name="Pending", hash="h2", path="/source/p.mkv", size=100)
    db.insert_entry(conn, e1)
    db.insert_entry(conn, e2)
    db.insert_progress(conn, Progress(uuid=e1.uuid, status=FileStatus.DONE))
    db.insert_progress(conn, Progress(uuid=e2.uuid, status=FileStatus.PENDING))

    best = db.query_best_candidate(conn)
    assert best is not None
    assert best.name == "Pending"


def test_query_best_candidate_none():
    conn = _in_memory_db()
    assert db.query_best_candidate(conn) is None


def test_has_active_queue_false():
    conn = _in_memory_db()
    e = Entry.new(name="Movie", hash="h1", path="/source/m.mkv", size=100)
    db.insert_entry(conn, e)
    db.insert_progress(conn, Progress(uuid=e.uuid, status=FileStatus.PENDING))
    assert db.has_active_queue(conn) is False


def test_has_active_queue_true():
    conn = _in_memory_db()
    e = Entry.new(name="Movie", hash="h1", path="/source/m.mkv", size=100)
    db.insert_entry(conn, e)
    db.insert_progress(conn, Progress(uuid=e.uuid, status=FileStatus.QUEUED))
    assert db.has_active_queue(conn) is True


def test_count_by_status():
    conn = _in_memory_db()
    for name, hash_, status in [
        ("A", "h1", FileStatus.PENDING),
        ("B", "h2", FileStatus.PENDING),
        ("C", "h3", FileStatus.DONE),
    ]:
        e = Entry.new(name=name, hash=hash_, path=f"/source/{name}.mkv", size=100)
        db.insert_entry(conn, e)
        db.insert_progress(conn, Progress(uuid=e.uuid, status=status))

    counts = db.count_by_status(conn)
    assert counts["pending"] == 2
    assert counts["done"] == 1


# ── Composite insert ─────────────────────────────────────────────────────────

def test_insert_new_file():
    conn = _in_memory_db()
    e = Entry.new(name="Movie", hash="h1", path="/source/m.mkv", size=100)
    meta = Metadata(uuid=e.uuid, kind=MetadataKind.DECLARED, codec="h264")
    db.insert_new_file(conn, e, meta)

    # Entry exists
    assert db.get_entry_by_uuid(conn, e.uuid) is not None
    # Metadata exists
    assert db.get_metadata(conn, e.uuid, MetadataKind.DECLARED) is not None
    # Progress exists with PENDING status
    p = db.get_progress(conn, e.uuid)
    assert p is not None
    assert p.status == FileStatus.PENDING
