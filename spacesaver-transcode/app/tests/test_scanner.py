"""Tests for scanner.py — scan_sources with mocked dependencies."""

import os
import tempfile
from unittest.mock import MagicMock

import sqlite3

import db
from models import DeclaredMetadata, Entry, FileStatus, MetadataKind
from scanner import ScanResult, scan_sources


def _in_memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(db._SCHEMA_SQL)
    return conn


def test_scan_empty_dir():
    """Scanning an empty directory should add nothing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        conn = _in_memory_db()
        result = scan_sources([tmpdir], conn)
        assert result.added == 0
        assert result.skipped == 0
        assert result.errors == 0


def test_scan_discovers_files():
    """Scanning a directory with media files should insert them."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create fake media files
        for name in ["movie1.mkv", "movie2.mp4", "readme.txt"]:
            path = os.path.join(tmpdir, name)
            with open(path, "wb") as f:
                f.write(b"x" * 1024)

        conn = _in_memory_db()
        result = scan_sources(
            [tmpdir],
            conn,
            hasher=lambda p: f"hash_{os.path.basename(p)}",
            classify_fn=lambda f: DeclaredMetadata(codec="h264"),
            clean_fn=lambda f: os.path.splitext(f)[0].replace(".", " ").title(),
        )

        # Should discover 2 media files (.mkv and .mp4), skip .txt
        assert result.added == 2
        assert result.skipped == 0
        assert result.errors == 0

        entries = db.list_entries(conn)
        assert len(entries) == 2


def test_scan_skips_existing():
    """Files already in the DB (by hash+path) should be skipped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "movie.mkv")
        with open(path, "wb") as f:
            f.write(b"x" * 1024)

        conn = _in_memory_db()
        fake_hash = "hash_movie.mkv"

        # Pre-insert the file
        e = Entry.new(name="Movie", hash=fake_hash, path=path, size=1024)
        from models import Metadata
        meta = Metadata(uuid=e.uuid, kind=MetadataKind.DECLARED, codec="h264")
        db.insert_new_file(conn, e, meta)

        result = scan_sources(
            [tmpdir],
            conn,
            hasher=lambda p: fake_hash,
            classify_fn=lambda f: DeclaredMetadata(codec="h264"),
            clean_fn=lambda f: "Movie",
        )

        assert result.added == 0
        assert result.skipped == 1


def test_scan_counts_errors():
    """Hash failures should be counted as errors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "movie.mkv")
        with open(path, "wb") as f:
            f.write(b"x" * 1024)

        conn = _in_memory_db()

        def failing_hasher(p):
            raise OSError("Permission denied")

        result = scan_sources(
            [tmpdir],
            conn,
            hasher=failing_hasher,
            classify_fn=lambda f: DeclaredMetadata(),
            clean_fn=lambda f: "Movie",
        )

        assert result.errors == 1
        assert result.added == 0


def test_scan_nonexistent_dir():
    """Scanning a nonexistent directory should not error but log a warning."""
    conn = _in_memory_db()
    result = scan_sources(["/nonexistent/dir"], conn)
    assert result.added == 0


def test_scan_nested_dirs():
    """Scanner should recurse into subdirectories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subdir = os.path.join(tmpdir, "Season 1")
        os.makedirs(subdir)
        for name in ["ep01.mkv", "ep02.mkv"]:
            with open(os.path.join(subdir, name), "wb") as f:
                f.write(b"x" * 512)

        conn = _in_memory_db()
        result = scan_sources(
            [tmpdir],
            conn,
            hasher=lambda p: f"hash_{os.path.basename(p)}",
            classify_fn=lambda f: DeclaredMetadata(),
            clean_fn=lambda f: os.path.splitext(f)[0],
        )

        assert result.added == 2
