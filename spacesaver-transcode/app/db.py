"""
db.py — SQLite persistence layer for SpaceSaver.

Database location: /dest/.transcoder/state.db
Schema is created on first run. All operations are thread-safe via a module-level lock.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from typing import List, Optional

from models import FileStatus, MediaFile, MediaType

log = logging.getLogger(__name__)

DB_DIR = "/dest/.transcoder"
DB_PATH = os.path.join(DB_DIR, "state.db")

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create database directory and schema if they don't already exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                uuid            TEXT PRIMARY KEY,
                file_hash       TEXT UNIQUE NOT NULL,
                source_path     TEXT NOT NULL,
                dest_path       TEXT NOT NULL,
                media_type      TEXT NOT NULL,
                clean_title     TEXT NOT NULL,
                year_or_episode TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                progress        REAL NOT NULL DEFAULT 0.0,
                error_count     INTEGER NOT NULL DEFAULT 0,
                error_msg       TEXT,
                tv_crf          INTEGER,
                movie_crf       INTEGER,
                tv_res_cap      INTEGER,
                movie_res_cap   INTEGER
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_status ON files(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hash ON files(file_hash)"
        )
        conn.commit()
    log.info("Database initialised at %s", DB_PATH)


def _row_to_media_file(row: sqlite3.Row) -> MediaFile:
    return MediaFile(
        uuid=row["uuid"],
        file_hash=row["file_hash"],
        source_path=row["source_path"],
        dest_path=row["dest_path"],
        media_type=MediaType(row["media_type"]),
        clean_title=row["clean_title"],
        year_or_episode=row["year_or_episode"],
        status=FileStatus(row["status"]),
        progress=row["progress"],
        error_count=row["error_count"],
        error_msg=row["error_msg"],
        tv_crf=row["tv_crf"],
        movie_crf=row["movie_crf"],
        tv_res_cap=row["tv_res_cap"],
        movie_res_cap=row["movie_res_cap"],
    )


def insert_file(mf: MediaFile) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO files
                (uuid, file_hash, source_path, dest_path, media_type,
                 clean_title, year_or_episode, status, progress,
                 error_count, error_msg, tv_crf, movie_crf, tv_res_cap, movie_res_cap)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mf.uuid, mf.file_hash, mf.source_path, mf.dest_path,
                mf.media_type.value, mf.clean_title, mf.year_or_episode,
                mf.status.value, mf.progress, mf.error_count, mf.error_msg,
                mf.tv_crf, mf.movie_crf, mf.tv_res_cap, mf.movie_res_cap,
            ),
        )
        conn.commit()


def update_status(uuid: str, status: FileStatus, progress: float = 0.0) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE files SET status = ?, progress = ? WHERE uuid = ?",
            (status.value, progress, uuid),
        )
        conn.commit()


def update_progress(uuid: str, progress: float) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE files SET progress = ? WHERE uuid = ?",
            (progress, uuid),
        )
        conn.commit()


def update_error(uuid: str, msg: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            UPDATE files
            SET status = ?, error_count = error_count + 1, error_msg = ?
            WHERE uuid = ?
            """,
            (FileStatus.ERROR.value, msg, uuid),
        )
        conn.commit()


def update_quality_override(uuid: str, overrides: dict) -> None:
    allowed = {"tv_crf", "movie_crf", "tv_res_cap", "movie_res_cap"}
    fields = {k: v for k, v in overrides.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with _lock, _connect() as conn:
        conn.execute(
            f"UPDATE files SET {set_clause} WHERE uuid = ?",  # noqa: S608
            (*fields.values(), uuid),
        )
        conn.commit()


def reset_file(uuid: str) -> bool:
    """Clear error state and requeue a failed file. Returns True if found."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "SELECT status FROM files WHERE uuid = ?", (uuid,)
        )
        row = cur.fetchone()
        if row is None:
            return False
        conn.execute(
            """
            UPDATE files
            SET status = ?, progress = 0.0, error_count = 0, error_msg = NULL
            WHERE uuid = ?
            """,
            (FileStatus.PENDING.value, uuid),
        )
        conn.commit()
    return True



def skip_file(uuid: str) -> bool:
    """Permanently skip a file. Returns True if found."""
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT uuid FROM files WHERE uuid = ?", (uuid,))
        if cur.fetchone() is None:
            return False
        conn.execute(
            "UPDATE files SET status = ? WHERE uuid = ?",
            (FileStatus.SKIPPED.value, uuid),
        )
        conn.commit()
    return True


def get_by_uuid(uuid: str) -> Optional[MediaFile]:
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT * FROM files WHERE uuid = ?", (uuid,))
        row = cur.fetchone()
    return _row_to_media_file(row) if row else None


def get_by_hash(file_hash: str) -> Optional[MediaFile]:
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT * FROM files WHERE file_hash = ?", (file_hash,))
        row = cur.fetchone()
    return _row_to_media_file(row) if row else None


def list_all() -> List[MediaFile]:
    with _lock, _connect() as conn:
        cur = conn.execute("SELECT * FROM files ORDER BY rowid ASC")
        rows = cur.fetchall()
    return [_row_to_media_file(r) for r in rows]


def list_by_status(status: FileStatus) -> List[MediaFile]:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM files WHERE status = ? ORDER BY rowid ASC",
            (status.value,),
        )
        rows = cur.fetchall()
    return [_row_to_media_file(r) for r in rows]


def count_by_status() -> dict:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM files GROUP BY status"
        )
        rows = cur.fetchall()
    return {row["status"]: row["cnt"] for row in rows}


def reset_in_progress() -> int:
    """On startup, reset any IN_PROGRESS files back to PENDING."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE files SET status = ?, progress = 0.0 WHERE status = ?",
            (FileStatus.PENDING.value, FileStatus.IN_PROGRESS.value),
        )
        conn.commit()
    count = cur.rowcount
    if count:
        log.warning("Reset %d in-progress file(s) to pending on startup", count)
    return count
