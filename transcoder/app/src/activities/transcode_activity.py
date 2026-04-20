import asyncio
import shutil
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
from models.quality import QualitySettings, load_quality


@dataclass
class TranscodeActivity(Activity):
    db: Database | None = None
    _target: Path | None = None
    _record: ListItem | None = None
    _abort_flag: asyncio.Event = field(default_factory=asyncio.Event)
    _quality: QualitySettings | None = None
    _cache_path: Path | None = None

    # Live progress — read by StatusActivity via /status
    progress_percent: float = 0.0
    progress_current_frame: int = 0
    progress_total_frames: int = 0
    quality_preset: str = ""

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
            and self._quality is not None
        )

    @override
    async def setup(
        self,
        db: Database,
        hash: str,
        quality: QualitySettings | None = None,
        cache_path: Path | None = None,
    ) -> bool:
        self.db = db
        self._abort_flag.clear()

        if not await asyncio.to_thread(prober.check_executable):
            logger.error("Transcode requested, but ffmpeg not found on system.")
            return False

        valid_items = await asyncio.to_thread(read_list_items, db, item_hash=hash)

        if len(valid_items) != 1:
            logger.error(
                f"Transcode of {hash} requested but found {len(valid_items)} matches."
            )
            return False

        self._record = valid_items[0]
        self._target = Path(self._record.path)

        # Resolve quality: explicit > persisted default (high)
        if quality is not None:
            self._quality = quality
            self.quality_preset = "custom"
        elif cache_path is not None:
            state = await asyncio.to_thread(load_quality, cache_path)
            self._quality = state.settings
            self.quality_preset = state.active_preset.value if state.active_preset else "custom"
        else:
            self._quality = QualitySettings()  # high preset defaults
            self.quality_preset = "high"

        self._cache_path = cache_path
        return True

    async def _set_status(self, status: WorkItemStatus) -> None:
        """Helper to instantly update the database with the new status."""
        if self.db and self._record:
            self._record.status = status
            await asyncio.to_thread(upsert_list_item, self.db, self._record)
            logger.debug(f"[{self._record.hash}] Status changed to: {status.value}")

    @override
    async def run(self) -> None:
        if not self.valid:
            logger.error(f"Transcode target invalid or missing: {self._target}")
            await self._set_status(WorkItemStatus.ERROR)
            return

        assert self._target is not None
        assert self._quality is not None

        def live_updater(percent: float, current_frame: int, total_frames: int):
            self.progress_percent = percent
            self.progress_current_frame = current_frame
            self.progress_total_frames = total_frames

        # Place the temp file in the cache directory (if available) to avoid
        # filling up /media during the transcode.
        if self._cache_path:
            await asyncio.to_thread(self._cache_path.mkdir, parents=True, exist_ok=True)
            temp_output = self._cache_path / f"{self._target.stem}.tmp.mkv"
        else:
            temp_output = self._target.with_suffix(".tmp.mkv")

        logger.info(
            f"Starting transcode of {self._target.name} "
            f"(crf={self._quality.crf}, preset={self._quality.preset}, "
            f"res_cap={self._quality.resolution_cap})"
        )
        await self._set_status(WorkItemStatus.PROCESSING)

        try:
            await transcode_file(
                input_path=self._target,
                output_path=temp_output,
                crf=self._quality.crf,
                preset=self._quality.preset,
                audio_bitrate=self._quality.audio_bitrate,
                resolution_cap=self._quality.resolution_cap,
                progress_callback=live_updater,
                cancel_event=self._abort_flag,
            )

            # Success! Move the result back to the source directory.
            final_output = self._target.with_suffix(".mkv")
            if await asyncio.to_thread(temp_output.exists):
                # shutil.move handles cross-device moves (cache → media)
                await asyncio.to_thread(shutil.move, str(temp_output), str(final_output))
                if self._target != final_output:
                    await asyncio.to_thread(self._target.unlink, missing_ok=True)

            logger.info(f"Transcode complete! Saved as {final_output.name}")

            # Update database record
            self._record.path = str(final_output)
            self._record.size = (await asyncio.to_thread(final_output.stat)).st_size
            await self._set_status(WorkItemStatus.DONE)

        except asyncio.CancelledError:
            logger.warning(f"Transcode cancelled for {self._target.name}")
            if await asyncio.to_thread(temp_output.exists):
                await asyncio.to_thread(temp_output.unlink)
            # Status was already set to ABORTED in cancel() via _set_status if it was called there? 
            # Wait, cancel() needs to be async if it calls _set_status? 
            # The base Activity says cancel() is sync.
            # I should probably update cancel to be sync but it can't await.

        except Exception as e:
            logger.error(f"Transcode failed for {self._target.name}: {e}")
            if await asyncio.to_thread(temp_output.exists):
                await asyncio.to_thread(temp_output.unlink)
            await self._set_status(WorkItemStatus.ERROR)

    @override
    def cancel(self) -> None:
        logger.info("Cancel requested. Stopping transcode...")
        self._abort_flag.set()
        # We can't await _set_status here because cancel is sync.
        # But we want the status to be updated.
        # Maybe use asyncio.create_task if there is a loop?
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._set_status(WorkItemStatus.ABORTED))
        except RuntimeError:
            # No loop running, fallback (might happen during shutdown)
            pass

    @override
    def result(self):
        return None
