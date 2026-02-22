"""Tests for scanner.py — scan_sources with mocked dependencies."""

import os
import tempfile
from unittest.mock import MagicMock

import sqlite3

import db
from models import DeclaredMetadata, Entry, FileStatus, Metadata, MetadataKind
from scanner import ScanResult, scan_sources


def _in_memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(db._SCHEMA_SQL)
    return conn


def _dummy_probe(uuid: str, path: str) -> Metadata:
    """A stub prober for tests — returns an ACTUAL metadata row with defaults."""
    return Metadata(uuid=uuid, kind=MetadataKind.ACTUAL)


def test_scan_empty_dir():
    """Scanning an empty directory should add nothing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        conn = _in_memory_db()
        result = scan_sources([tmpdir], conn, probe_fn=_dummy_probe)
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
            probe_fn=_dummy_probe,
        )

        # Should discover 2 media files (.mkv and .mp4), skip .txt
        assert result.added == 2
        assert result.skipped == 0
        assert result.errors == 0

        entries = db.list_entries(conn)
        assert len(entries) == 2


def test_scan_inserts_actual_metadata():
    """Scanner should insert both DECLARED and ACTUAL metadata rows."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "movie.mkv")
        with open(path, "wb") as f:
            f.write(b"x" * 1024)

        conn = _in_memory_db()

        def custom_probe(uuid, p):
            return Metadata(uuid=uuid, kind=MetadataKind.ACTUAL, codec="hevc", resolution="1920x1080")

        result = scan_sources(
            [tmpdir],
            conn,
            hasher=lambda p: "hash1",
            classify_fn=lambda f: DeclaredMetadata(codec="h264"),
            clean_fn=lambda f: "Movie",
            probe_fn=custom_probe,
        )

        assert result.added == 1
        entries = db.list_entries(conn)
        uuid = entries[0].uuid

        # Both metadata kinds should exist
        all_meta = db.get_all_metadata(conn, uuid)
        assert len(all_meta) == 2
        kinds = {m.kind for m in all_meta}
        assert MetadataKind.DECLARED in kinds
        assert MetadataKind.ACTUAL in kinds

        # ACTUAL metadata should have the probed values
        actual = db.get_metadata(conn, uuid, MetadataKind.ACTUAL)
        assert actual.codec == "hevc"
        assert actual.resolution == "1920x1080"


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
        meta = Metadata(uuid=e.uuid, kind=MetadataKind.DECLARED, codec="h264")
        db.insert_new_file(conn, e, [meta])

        result = scan_sources(
            [tmpdir],
            conn,
            hasher=lambda p: fake_hash,
            classify_fn=lambda f: DeclaredMetadata(codec="h264"),
            clean_fn=lambda f: "Movie",
            probe_fn=_dummy_probe,
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
            probe_fn=_dummy_probe,
        )

        assert result.errors == 1
        assert result.added == 0


def test_scan_nonexistent_dir():
    """Scanning a nonexistent directory should not error but log a warning."""
    conn = _in_memory_db()
    result = scan_sources(["/nonexistent/dir"], conn, probe_fn=_dummy_probe)
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
            probe_fn=_dummy_probe,
        )

        assert result.added == 2
