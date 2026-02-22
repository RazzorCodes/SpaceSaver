"""
scanner.py — One-shot source directory scanner for SpaceSaver.

Behaviour (startup only):
  - Walk configured source directories once
  - Compute hash + size for each candidate file
  - Match against existing entries by hash + path
  - Insert newly discovered files as PENDING
  - Do not re-insert or update files already present and unchanged
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Callable, List

import classifier
import db
import prober
from hash import compute_hash
from models import Entry

log = logging.getLogger(__name__)

MEDIA_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".wmv"}


@dataclass
class ScanResult:
    added: int = 0
    skipped: int = 0
    errors: int = 0


def scan_sources(
    source_dirs: List[str],
    conn: sqlite3.Connection,
    hasher: Callable[[str], str] = compute_hash,
    classify_fn: Callable[[str], object] = classifier.classify,
    clean_fn: Callable[[str], str] = classifier.clean_filename,
    probe_fn: Callable[[str, str], object] = prober.extract_actual_metadata,
) -> ScanResult:
    """
    Scan source directories once and insert newly discovered files.

    All dependencies are injected for testability:
      - conn:        SQLite connection
      - hasher:      function(path) -> hash string
      - classify_fn: function(filename) -> DeclaredMetadata
      - clean_fn:    function(filename) -> cleaned name string
      - probe_fn:    function(uuid, path) -> Metadata (ACTUAL)
    """
    # <telemetry>: startup_scan_started — beginning source directory scan
    log.info("[startup_flow] event=startup_scan_started source_dirs=%s", source_dirs)

    result = ScanResult()

    for source_dir in source_dirs:
        if not os.path.isdir(source_dir):
            log.warning("[startup_flow] event=scan_dir_missing dir=%s", source_dir)
            continue

        for root, _dirs, files in os.walk(source_dir):
            # Limit depth to 3 levels relative to source_dir
            rel_path = os.path.relpath(root, source_dir)
            if rel_path == ".":
                depth = 0
            else:
                depth = rel_path.count(os.sep) + 1

            if depth >= 3:
                _dirs.clear()  # Do not descend further
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in MEDIA_EXTENSIONS:
                    continue

                path = os.path.join(root, fname)

                # Compute hash + size
                try:
                    file_hash = hasher(path)
                    file_size = os.path.getsize(path)
                except OSError as exc:
                    log.warning(
                        "[startup_flow] event=scan_file_error path=%s error=%s",
                        path, exc,
                    )
                    result.errors += 1
                    continue

                # Check if already in DB by hash + path
                existing = db.get_entry_by_hash_and_path(conn, file_hash, path)
                if existing is not None:
                    result.skipped += 1
                    continue

                # Classify filename (defensive — never throws)
                declared = classify_fn(fname)

                # Clean the filename for the name column
                clean_name = clean_fn(fname)

                # Create entry
                entry = Entry.new(
                    name=clean_name,
                    hash=file_hash,
                    path=path,
                    size=file_size,
                )

                # Convert declared metadata to a Metadata row
                meta_declared = declared.to_metadata(entry.uuid)

                # Execute prober for ACTUAL metadata
                meta_actual = probe_fn(entry.uuid, path)

                # Insert entry + both metadata blocks + progress(PENDING)
                db.insert_new_file(conn, entry, [meta_declared, meta_actual])

                # <telemetry>: classifier_result(uuid=<uuid>, declared_fields_parsed=N, fields_unknown=N)
                log.info(
                    "[startup_flow] event=classifier_result uuid=%s "
                    "declared_fields_parsed=%d fields_unknown=%d actual_codec=%s",
                    entry.uuid, declared.parsed_field_count, declared.unknown_field_count,
                    meta_actual.codec,
                )

                result.added += 1
                log.info(
                    "[startup_flow] event=file_discovered uuid=%s name=%s size=%d",
                    entry.uuid, clean_name, file_size,
                )

    # <telemetry>: startup_scan_completed(added=N, skipped=N, errors=N)
    log.info(
        "[startup_flow] event=startup_scan_completed added=%d skipped=%d errors=%d",
        result.added, result.skipped, result.errors,
    )

    return result
