"""
db.py — SQLite persistence layer for SpaceSaver (database-first architecture).

Database location: /dest/.transcoder/state.db
Normalised schema: entries, metadata, progress.
Schema validation on startup: drop-and-recreate if mismatch.
All operations are thread-safe via a module-level lock.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from typing import Dict, List, Optional

from models import (
    DeclaredMetadata,
    Entry,
    FileStatus,
    Metadata,
    MetadataKind,
    Progress,
)

log = logging.getLogger(__name__)

DB_DIR = "/dest/.transcoder"
DB_PATH = os.path.join(DB_DIR, "state.db")

_lock = threading.Lock()

# ── Expected schema SQL ──────────────────────────────────────────────────────

_SCHEMA_SQL = """\
CREATE TABLE entries (uuid TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT NOT NULL, path TEXT NOT NULL, size INTEGER NOT NULL);
CREATE TABLE metadata (uuid TEXT NOT NULL REFERENCES entries(uuid), kind TEXT NOT NULL, codec TEXT NOT NULL DEFAULT 'Unknown', format TEXT NOT NULL DEFAULT 'Unknown', sar TEXT NOT NULL DEFAULT 'Unknown', dar TEXT NOT NULL DEFAULT 'Unknown', resolution TEXT NOT NULL DEFAULT 'Unknown', framerate REAL NOT NULL DEFAULT 0.0, extra TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (uuid, kind));
CREATE TABLE progress (uuid TEXT PRIMARY KEY REFERENCES entries(uuid), status TEXT NOT NULL DEFAULT 'pending', progress REAL NOT NULL DEFAULT 0.0, frame_current INTEGER NOT NULL DEFAULT 0, frame_total INTEGER NOT NULL DEFAULT 0, workfile TEXT);
CREATE INDEX idx_entries_hash ON entries(hash);
CREATE INDEX idx_entries_path ON entries(path);
CREATE INDEX idx_entries_size_desc ON entries(size DESC);
CREATE INDEX idx_progress_status ON progress(status);
"""

# Normalised representation used for schema comparison
_EXPECTED_TABLES = {
    "entries": (
        "CREATE TABLE entries ("
        "uuid TEXT PRIMARY KEY, "
        "name TEXT NOT NULL, "
        "hash TEXT NOT NULL, "
        "path TEXT NOT NULL, "
        "size INTEGER NOT NULL)"
    ),
    "metadata": (
        "CREATE TABLE metadata ("
        "uuid TEXT NOT NULL REFERENCES entries(uuid), "
        "kind TEXT NOT NULL, "
        "codec TEXT NOT NULL DEFAULT 'Unknown', "
        "format TEXT NOT NULL DEFAULT 'Unknown', "
        "sar TEXT NOT NULL DEFAULT 'Unknown', "
        "dar TEXT NOT NULL DEFAULT 'Unknown', "
        "resolution TEXT NOT NULL DEFAULT 'Unknown', "
        "framerate REAL NOT NULL DEFAULT 0.0, "
        "extra TEXT NOT NULL DEFAULT '{}', "
        "PRIMARY KEY (uuid, kind))"
    ),
    "progress": (
        "CREATE TABLE progress ("
        "uuid TEXT PRIMARY KEY REFERENCES entries(uuid), "
        "status TEXT NOT NULL DEFAULT 'pending', "
        "progress REAL NOT NULL DEFAULT 0.0, "
        "frame_current INTEGER NOT NULL DEFAULT 0, "
        "frame_total INTEGER NOT NULL DEFAULT 0, "
        "workfile TEXT)"
    ),
}


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _normalise_sql(sql: str) -> str:
    """Collapse whitespace for schema comparison."""
    return " ".join(sql.split())


# ── Schema validation ────────────────────────────────────────────────────────

def validate_schema(conn: sqlite3.Connection) -> bool:
    """
    Compare the current DB schema against the expected definition.
    If mismatch: drop all tables and recreate.

    Returns True if schema was already valid, False if it was dropped/recreated.
    """
    cur = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?)",
        ("entries", "metadata", "progress"),
    )
    existing = {row["name"]: _normalise_sql(row["sql"]) for row in cur.fetchall()}

    # Check each table
    match = True
    for table_name, expected_sql in _EXPECTED_TABLES.items():
        actual_sql = existing.get(table_name)
        if actual_sql is None or actual_sql != _normalise_sql(expected_sql):
            match = False
            break

    if match and len(existing) == len(_EXPECTED_TABLES):
        # <telemetry>: db_schema_validated — schema matches expected definition
        log.info("[startup_flow] event=db_schema_validated")
        return True

    # Schema mismatch — drop and recreate
    # <telemetry>: db_schema_mismatch_dropped — schema did not match, dropping all tables
    log.warning("[startup_flow] event=db_schema_mismatch_dropped existing_tables=%s", list(existing.keys()))
    conn.execute("DROP TABLE IF EXISTS metadata")
    conn.execute("DROP TABLE IF EXISTS progress")
    conn.execute("DROP TABLE IF EXISTS entries")
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    return False


# ── Initialisation ───────────────────────────────────────────────────────────

def init_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create database directory, connect, and validate/create schema."""
    path = db_path or DB_PATH
    db_dir = os.path.dirname(path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with _lock:
        conn = _connect(path)
        validate_schema(conn)
    log.info("Database initialised at %s", path)
    return conn


# ── Entry operations ─────────────────────────────────────────────────────────

def insert_entry(conn: sqlite3.Connection, entry: Entry) -> None:
    """Insert a new entry row. Ignores if uuid already exists."""
    with _lock:
        conn.execute(
            "INSERT OR IGNORE INTO entries (uuid, name, hash, path, size) VALUES (?, ?, ?, ?, ?)",
            (entry.uuid, entry.name, entry.hash, entry.path, entry.size),
        )
        conn.commit()


def get_entry_by_uuid(conn: sqlite3.Connection, uuid: str) -> Optional[Entry]:
    with _lock:
        cur = conn.execute("SELECT * FROM entries WHERE uuid = ?", (uuid,))
        row = cur.fetchone()
    if row is None:
        return None
    return Entry(uuid=row["uuid"], name=row["name"], hash=row["hash"],
                 path=row["path"], size=row["size"])


def get_entry_by_hash_and_path(conn: sqlite3.Connection, hash: str, path: str) -> Optional[Entry]:
    with _lock:
        cur = conn.execute(
            "SELECT * FROM entries WHERE hash = ? AND path = ?", (hash, path)
        )
        row = cur.fetchone()
    if row is None:
        return None
    return Entry(uuid=row["uuid"], name=row["name"], hash=row["hash"],
                 path=row["path"], size=row["size"])


def list_entries(conn: sqlite3.Connection) -> List[Entry]:
    with _lock:
        cur = conn.execute("SELECT * FROM entries ORDER BY rowid ASC")
        rows = cur.fetchall()
    return [
        Entry(uuid=r["uuid"], name=r["name"], hash=r["hash"],
              path=r["path"], size=r["size"])
        for r in rows
    ]


# ── Metadata operations ─────────────────────────────────────────────────────

def insert_metadata(conn: sqlite3.Connection, meta: Metadata) -> None:
    """Insert or replace a metadata row."""
    extra_json = json.dumps(meta.extra) if isinstance(meta.extra, dict) else meta.extra
    with _lock:
        conn.execute(
            """INSERT OR REPLACE INTO metadata
               (uuid, kind, codec, format, sar, dar, resolution, framerate, extra)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (meta.uuid, meta.kind.value, meta.codec, meta.format,
             meta.sar, meta.dar, meta.resolution, meta.framerate, extra_json),
        )
        conn.commit()


def get_metadata(conn: sqlite3.Connection, uuid: str, kind: MetadataKind) -> Optional[Metadata]:
    with _lock:
        cur = conn.execute(
            "SELECT * FROM metadata WHERE uuid = ? AND kind = ?",
            (uuid, kind.value),
        )
        row = cur.fetchone()
    if row is None:
        return None
    extra = json.loads(row["extra"]) if row["extra"] else {}
    return Metadata(
        uuid=row["uuid"],
        kind=MetadataKind(row["kind"]),
        codec=row["codec"],
        format=row["format"],
        sar=row["sar"],
        dar=row["dar"],
        resolution=row["resolution"],
        framerate=row["framerate"],
        extra=extra,
    )


def get_all_metadata(conn: sqlite3.Connection, uuid: str) -> List[Metadata]:
    with _lock:
        cur = conn.execute("SELECT * FROM metadata WHERE uuid = ?", (uuid,))
        rows = cur.fetchall()
    result = []
    for row in rows:
        extra = json.loads(row["extra"]) if row["extra"] else {}
        result.append(Metadata(
            uuid=row["uuid"],
            kind=MetadataKind(row["kind"]),
            codec=row["codec"],
            format=row["format"],
            sar=row["sar"],
            dar=row["dar"],
            resolution=row["resolution"],
            framerate=row["framerate"],
            extra=extra,
        ))
    return result


# ── Progress operations ──────────────────────────────────────────────────────

def insert_progress(conn: sqlite3.Connection, progress: Progress) -> None:
    """Insert a new progress row. Ignores if uuid already exists."""
    with _lock:
        conn.execute(
            """INSERT OR IGNORE INTO progress
               (uuid, status, progress, frame_current, frame_total, workfile)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (progress.uuid, progress.status.value, progress.progress,
             progress.frame_current, progress.frame_total, progress.workfile),
        )
        conn.commit()


def get_progress(conn: sqlite3.Connection, uuid: str) -> Optional[Progress]:
    with _lock:
        cur = conn.execute("SELECT * FROM progress WHERE uuid = ?", (uuid,))
        row = cur.fetchone()
    if row is None:
        return None
    return Progress(
        uuid=row["uuid"],
        status=FileStatus(row["status"]),
        progress=row["progress"],
        frame_current=row["frame_current"],
        frame_total=row["frame_total"],
        workfile=row["workfile"],
    )


def set_status(conn: sqlite3.Connection, uuid: str, status: FileStatus) -> None:
    with _lock:
        conn.execute(
            "UPDATE progress SET status = ? WHERE uuid = ?",
            (status.value, uuid),
        )
        conn.commit()


def update_progress(conn: sqlite3.Connection, uuid: str, **fields) -> None:
    """Update one or more fields on the progress row."""
    allowed = {"status", "progress", "frame_current", "frame_total", "workfile"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    # Convert enum to value
    if "status" in updates and isinstance(updates["status"], FileStatus):
        updates["status"] = updates["status"].value
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [uuid]
    with _lock:
        conn.execute(
            f"UPDATE progress SET {set_clause} WHERE uuid = ?",  # noqa: S608
            values,
        )
        conn.commit()


# ── Query helpers ────────────────────────────────────────────────────────────

def query_best_candidate(conn: sqlite3.Connection) -> Optional[Entry]:
    """
    Find the best PENDING entry: join progress for status=PENDING,
    order by entries.size DESC, take first.
    """
    with _lock:
        cur = conn.execute(
            """SELECT e.* FROM entries e
               JOIN progress p ON e.uuid = p.uuid
               WHERE p.status = ?
               ORDER BY e.size DESC
               LIMIT 1""",
            (FileStatus.PENDING.value,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return Entry(uuid=row["uuid"], name=row["name"], hash=row["hash"],
                 path=row["path"], size=row["size"])


def has_active_queue(conn: sqlite3.Connection) -> bool:
    """Return True if any item is QUEUED or IN_PROGRESS."""
    with _lock:
        cur = conn.execute(
            "SELECT COUNT(*) as cnt FROM progress WHERE status IN (?, ?)",
            (FileStatus.QUEUED.value, FileStatus.IN_PROGRESS.value),
        )
        row = cur.fetchone()
    return row["cnt"] > 0


def count_by_status(conn: sqlite3.Connection) -> Dict[str, int]:
    with _lock:
        cur = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM progress GROUP BY status"
        )
        rows = cur.fetchall()
    return {row["status"]: row["cnt"] for row in rows}


# ── Composite insert (convenience) ──────────────────────────────────────────

def insert_new_file(conn: sqlite3.Connection, entry: Entry, metadatas: List[Metadata]) -> None:
    """
    Insert a new file: entry row + metadata rows + progress row (PENDING).
    All in a single transaction.
    """
    with _lock:
        conn.execute(
            "INSERT OR IGNORE INTO entries (uuid, name, hash, path, size) VALUES (?, ?, ?, ?, ?)",
            (entry.uuid, entry.name, entry.hash, entry.path, entry.size),
        )
        for meta in metadatas:
            extra_json = json.dumps(meta.extra) if isinstance(meta.extra, dict) else meta.extra
            conn.execute(
                """INSERT OR REPLACE INTO metadata
                   (uuid, kind, codec, format, sar, dar, resolution, framerate, extra)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (meta.uuid, meta.kind.value, meta.codec,
                 meta.format, meta.sar, meta.dar,
                 meta.resolution, meta.framerate, extra_json),
            )
        conn.execute(
            """INSERT OR IGNORE INTO progress
               (uuid, status, progress, frame_current, frame_total, workfile)
               VALUES (?, ?, 0.0, 0, 0, NULL)""",
            (entry.uuid, FileStatus.PENDING.value),
        )
        conn.commit()
