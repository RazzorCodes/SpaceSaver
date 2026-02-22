"""Tests for models.py — Entry, Metadata, Progress, DeclaredMetadata."""

from models import (
    DeclaredMetadata,
    Entry,
    FileStatus,
    Metadata,
    MetadataKind,
    Progress,
    UNKNOWN_SENTINEL,
)


def test_entry_new():
    e = Entry.new(name="Inception", hash="abc123", path="/source/movie.mkv", size=1_000_000)
    assert e.name == "Inception"
    assert e.hash == "abc123"
    assert e.path == "/source/movie.mkv"
    assert e.size == 1_000_000
    assert len(e.uuid) == 36  # UUID format


def test_entry_to_dict():
    e = Entry(uuid="test-uuid", name="Inception", hash="abc", path="/source/m.mkv", size=500)
    d = e.to_dict()
    assert d["uuid"] == "test-uuid"
    assert d["name"] == "Inception"
    assert d["size"] == 500


def test_metadata_defaults():
    m = Metadata(uuid="test-uuid", kind=MetadataKind.DECLARED)
    assert m.codec == UNKNOWN_SENTINEL
    assert m.format == UNKNOWN_SENTINEL
    assert m.framerate == 0.0
    assert m.extra == {}


def test_metadata_to_dict():
    m = Metadata(uuid="u1", kind=MetadataKind.ACTUAL, codec="h265", resolution="1920x1080")
    d = m.to_dict()
    assert d["kind"] == "actual"
    assert d["codec"] == "h265"
    assert d["resolution"] == "1920x1080"


def test_progress_defaults():
    p = Progress(uuid="test-uuid")
    assert p.status == FileStatus.PENDING
    assert p.progress == 0.0
    assert p.frame_current == 0
    assert p.frame_total == 0
    assert p.workfile is None


def test_progress_to_dict():
    p = Progress(uuid="u1", status=FileStatus.IN_PROGRESS, progress=45.5, frame_current=1000, frame_total=2000)
    d = p.to_dict()
    assert d["status"] == "in_progress"
    assert d["progress"] == 45.5
    assert d["frame_current"] == 1000


def test_file_status_enum():
    assert FileStatus.UNKNOWN.value == "unknown"
    assert FileStatus.PENDING.value == "pending"
    assert FileStatus.QUEUED.value == "queued"
    assert FileStatus.IN_PROGRESS.value == "in_progress"
    assert FileStatus.OPTIMUM.value == "optimum"
    assert FileStatus.DONE.value == "done"


def test_declared_metadata_all_unknown():
    dm = DeclaredMetadata()
    assert dm.parsed_field_count == 0
    assert dm.unknown_field_count == 6


def test_declared_metadata_partial():
    dm = DeclaredMetadata(codec="h264", resolution="1920x1080")
    assert dm.parsed_field_count == 2
    assert dm.unknown_field_count == 4


def test_declared_metadata_to_metadata():
    dm = DeclaredMetadata(codec="h265", resolution="3840x2160", framerate="23.98")
    meta = dm.to_metadata("test-uuid")
    assert meta.uuid == "test-uuid"
    assert meta.kind == MetadataKind.DECLARED
    assert meta.codec == "h265"
    assert meta.framerate == 23.98
