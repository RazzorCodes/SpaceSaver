import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import override

import engine.probe as prober
from activities.activity import Activity
from data.db import Database
from data.db_op import read_list_items, upsert_list_item
from engine.transcode import transcode_file
from misc.logger import logger
from models.models import ListItem
from models.orm import WorkItemStatus


@dataclass
class TranscodeActivity(Activity):
    db: Database | None = None
    _target: Path | None = None
    _record: ListItem | None = None
    _abort_flag: threading.Event = field(default_factory=threading.Event)

    @property
    @override
    def type(self) -> str:
        return "tran"

    @property
    def valid(self) -> bool:
        return bool(
            self._target
            and self._target.exists()
            and self.db is not None
            and self._record is not None
        )

    def setup(self, db: Database, target_hash: str) -> bool:
        self.db = db
        self._abort_flag.clear()

        if not prober.check_executable():
            logger.error("Transcode requested, but ffmpeg not found on system.")
            return False

        valid_items = read_list_items(db, item_hash=target_hash)

        if len(valid_items) != 1:
            logger.error(
                f"Transcode of {target_hash} requested but found {len(valid_items)} matches."
            )
            return False

        self._record = valid_items[0]
        self._target = Path(self._record.path)
        return True

    def _set_status(self, status: WorkItemStatus) -> None:
        """Helper to instantly update the database with the new status."""
        if self.db and self._record:
            self._record.status = status
            upsert_list_item(self.db, self._record)
            logger.debug(f"[{self._record.hash}] Status changed to: {status.value}")

    def run(self) -> None:
        if not self.valid:
            logger.error(f"Transcode target invalid or missing: {self._target}")
            self._set_status(WorkItemStatus.ERROR)
            return

        def live_updater(percent: float, current_frame: int, total_frames: int):
            print(
                f"Progress: {percent:.1f}% ({current_frame}/{total_frames} frames)",
                end="\r",
                flush=True,
            )

        temp_output = self._target.with_suffix(".tmp.mkv")
        logger.info(f"Starting transcode of {self._target.name}")
        self._set_status(WorkItemStatus.PROCESSING)

        try:
            # Call the transcode block directly; the Governor already placed us in a thread!
            transcode_file(
                input_path=self._target,
                output_path=temp_output,
                crf=20,
                progress_callback=live_updater,
                cancel_event=self._abort_flag,
            )

            # Check if we were cancelled during the run
            if self._abort_flag.is_set():
                logger.warning(f"\nTranscode cancelled for {self._target.name}")
                if temp_output.exists():
                    temp_output.unlink()
                return  # Status was already set to ABORTED in cancel()

            # Success! Swap files
            final_output = self._target.with_suffix(".mkv")
            if temp_output.exists():
                temp_output.replace(final_output)
                if self._target != final_output:
                    self._target.unlink(missing_ok=True)

            logger.info(f"\nTranscode complete! Saved as {final_output.name}")

            # Update database record
            self._record.path = str(final_output)
            self._record.size = final_output.stat().st_size
            self._set_status(WorkItemStatus.DONE)

        except Exception as e:
            logger.error(f"\nTranscode failed for {self._target.name}: {e}")
            if temp_output.exists():
                temp_output.unlink()
            # Status will only be ERROR if it genuinely crashed
            self._set_status(WorkItemStatus.ERROR)

    def cancel(self) -> None:
        logger.info("Cancel requested. Stopping transcode...")
        self._abort_flag.set()
        self._set_status(WorkItemStatus.ABORTED)
