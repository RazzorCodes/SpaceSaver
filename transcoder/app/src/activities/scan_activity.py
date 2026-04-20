import asyncio
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import override

import engine.classifier as classifier
import engine.hash as hasher
import engine.probe as prober
from activities.activity import Activity
from data.db import Database
from data.db_op import create_list_item, upsert_list_item
from engine.list import list_path
from misc.logger import logger
from models.models import ListItem
from models.orm import WorkItemStatus

SCAN_FILES_EXTENSIONS = [".mkv", ".mp4", ".avi"]


@dataclass
class ScanActivity(Activity):
    db: Database | None = None
    _path: Path | None = None
    _probe: bool = False
    _abort_flag: asyncio.Event = field(default_factory=asyncio.Event)
    _thread_abort_flag: threading.Event = field(default_factory=threading.Event)

    @property
    @override
    def type(self) -> str:
        return "scan"

    @property
    def valid(self) -> bool:
        return bool(self._path and self._path.exists() and self.db is not None)

    @override
    async def setup(self, db: Database, path: Path, probe: bool = False) -> bool:
        self.db = db
        self._path = path
        self._probe = probe
        self._abort_flag.clear()
        self._thread_abort_flag.clear()

        if not path.exists():
            logger.warning(f"Scan activity set up with inexistent path: {self._path}")
            return False

        if self._probe and not await asyncio.to_thread(prober.check_executable):
            logger.error("Probe was requested, but ffprobe executable was not found.")
            return False

        return True

    @override
    async def run(self) -> None:
        if not self.valid:
            logger.error("Scan activity invalid: Missing path or database")
            return

        database = self.db

        def on_file_found(file_path: Path) -> None:
            if self._thread_abort_flag.is_set():
                return

            path_str = str(file_path)

            try:
                record = ListItem(
                    path=path_str,
                    hash=hasher.compute_hash(path_str),
                    status=WorkItemStatus.UNKNOWN,
                    name=classifier.clean_filename(path_str),
                    size=file_path.stat().st_size,
                )
            except (FileNotFoundError, OSError, RuntimeError) as e:
                logger.error(f"Failed to inspect {path_str}: {e}")
                return

            try:
                if self._probe and not self._thread_abort_flag.is_set():
                    record = prober.inspect(record)
            except Exception as e:
                logger.error(f"Prober failed on file {path_str}: {e}")
                record.status = WorkItemStatus.ERROR

            try:
                if record.status == WorkItemStatus.ERROR:
                    create_list_item(database, record)
                elif upsert_list_item(database, record):
                    logger.debug(f"Upserted DB record for: {file_path.name}")
                else:
                    logger.error(f"Failed to upsert DB record for: {file_path.name}")
            except Exception as e:
                logger.error(f"Failed to persist scan result for {path_str}: {e}")

        logger.info(f"Starting scan on {self._path}")

        files = await asyncio.to_thread(
            list_path,
            path=self._path,
            ext_wl=SCAN_FILES_EXTENSIONS,
            cancel=self._thread_abort_flag,
            on_item=on_file_found,
        )

        if self._abort_flag.is_set():
            logger.warning(
                f"Scan was canceled mid-way. Processed {len(files)} files before stopping."
            )
        else:
            logger.info(f"Scan complete. Found and processed {len(files)} files.")

    @override
    def cancel(self) -> None:
        """Triggers the abort flags, which tells the directory walker to stop."""
        logger.info("Cancel requested. Stopping scan...")
        self._abort_flag.set()
        self._thread_abort_flag.set()

    @override
    def result(self):
        return None
