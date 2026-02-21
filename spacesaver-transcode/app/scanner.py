"""
scanner.py — Background thread that watches the source library and enqueues new files.

Behaviour:
  - Walks /source on every rescan tick (default: 10 minutes)
  - Computes a fast hash for each candidate file
  - Skips files already recorded in the DB (any status) or in the flat file
  - New files are classified and inserted into the DB as PENDING
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Set

import classifier
import db
from config import cfg
from hash import compute_hash
from models import MediaFile

log = logging.getLogger(__name__)

SOURCE_DIR = "/source"
DEST_DIR = "/dest"
FLAT_FILE = os.path.join(DEST_DIR, ".spacesaver-transcode")

MEDIA_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".wmv"}

_stop_event = threading.Event()
_rescan_event = threading.Event()  # set to wake scanner before next interval


def _load_flat_file() -> Set[str]:
    """Return the set of hashes already recorded in the flat file."""
    hashes: Set[str] = set()
    if not os.path.exists(FLAT_FILE):
        return hashes
    try:
        with open(FLAT_FILE, "r") as f:
            for line in f:
                h = line.strip()
                if h:
                    hashes.add(h)
    except OSError as exc:
        log.warning("Could not read flat file: %s", exc)
    return hashes


def _dest_path(source_path: str, file_hash: str, clean_title: str, year_or_episode: str) -> str:
    """
    Mirror the source directory structure under /dest, but replace the
    filename with:  <hash>.<Clean Title>.<year_or_episode>.mkv
    """
    rel = os.path.relpath(source_path, SOURCE_DIR)
    rel_dir = os.path.dirname(rel)
    label_parts = [file_hash, clean_title]
    if year_or_episode:
        label_parts.append(year_or_episode)
    filename = ".".join(label_parts) + ".mkv"
    return os.path.join(DEST_DIR, rel_dir, filename)


def _scan_once() -> None:
    flat_hashes = _load_flat_file()
    found = 0

    for root, _dirs, files in os.walk(SOURCE_DIR):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in MEDIA_EXTENSIONS:
                continue

            path = os.path.join(root, fname)
            try:
                file_hash = compute_hash(path)
            except OSError as exc:
                log.warning("Cannot hash %s: %s", path, exc)
                continue

            # Skip if already in flat file (DONE) or DB
            if file_hash in flat_hashes:
                continue
            if db.get_by_hash(file_hash) is not None:
                continue

            # New file — classify and enqueue
            try:
                media_type, clean_title, year_or_episode = classifier.classify(path)
            except Exception as exc:  # noqa: BLE001
                log.warning("Cannot classify %s: %s", path, exc)
                continue

            dest_path = _dest_path(path, file_hash, clean_title, year_or_episode)
            mf = MediaFile.new(
                file_hash=file_hash,
                source_path=path,
                dest_path=dest_path,
                media_type=media_type,
                clean_title=clean_title,
                year_or_episode=year_or_episode,
            )
            db.insert_file(mf)
            found += 1
            log.info("Enqueued: %s (%s)", clean_title, media_type.value)

    log.info("Scan complete. %d new file(s) enqueued.", found)


def run() -> None:
    """Entry point for the scanner background thread."""
    log.info("Scanner started. Source: %s", SOURCE_DIR)
    while not _stop_event.is_set():
        try:
            _scan_once()
        except Exception as exc:  # noqa: BLE001
            log.exception("Scan error: %s", exc)
        # Wait for stop, an explicit rescan trigger, or the regular interval
        _rescan_event.wait(timeout=cfg.rescan_interval)
        _rescan_event.clear()
    log.info("Scanner stopped.")


def start() -> threading.Thread:
    t = threading.Thread(target=run, name="scanner", daemon=True)
    t.start()
    return t


def trigger_rescan() -> None:
    """Wake the scanner immediately without waiting for the next interval."""
    _rescan_event.set()


def stop() -> None:
    _stop_event.set()
