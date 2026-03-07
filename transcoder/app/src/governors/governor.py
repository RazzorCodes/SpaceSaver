import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from activities.scan_activity import ScanActivity
from activities.transcode_activity import TranscodeActivity
from data.db_op import read_list_items
from misc.logger import logger
from models.configuration import Configuration
from models.models import ListItem
from modules.database_module import DatabaseModule
from modules.endpoint_module import EndpointModule
from modules.worker_module import WorkerModule


class Governor:
    def __init__(self, config: Configuration):
        self._config = config
        self._db_mod = DatabaseModule()
        self._wk_mod = WorkerModule()
        self._ep_mod = EndpointModule()
        self._ready = False

        self._query_executor = ThreadPoolExecutor(max_workers=1)
        self._work_executor = ThreadPoolExecutor(max_workers=1)

    def setup(self) -> None:
        """Initializes the database and marks the Governor as ready."""
        # Assuming setup() returns a boolean
        self._ready = True
        self._ready &= self._db_mod.setup(self._config)
        self._ready &= self._wk_mod.setup(self._config)
        self._ready &= self._ep_mod.setup(self._config)
        if self._ready:
            logger.info("Governor setup complete and ready.")
        else:
            logger.error("Governor setup failed.")

    @property
    def ready(self) -> bool:
        return self._ready

    # --- API Request Handlers ---

    def start_scan(self, path: str | None = None) -> str:
        """Spawns a background scan and returns a tracking ID."""
        if not self.ready:
            raise RuntimeError("Governor is not ready.")

        scan_path = path or self._config.media_path

        # 1. Create a fresh activity for this specific request
        activity = ScanActivity()
        activity.setup(self._db_mod._database, scan_path, probe=True)

        # 2. Track it and throw it into the background thread pool

        return self._wk_mod.submit(activity)

    def start_transcode(
        self, target_hash: str
    ) -> str:  # remember to use a queue not paralel pool; limit to one th max
        """Spawns a background transcode and returns a tracking ID."""
        if not self.ready:
            raise RuntimeError("Governor is not ready.")

        activity = TranscodeActivity()
        if not activity.setup(self._db_mod._database, target_hash):
            raise ValueError(f"Failed to setup transcode for {target_hash}")

        return self._wk_mod.submit(activity)

    def get_status(self):
        return self._wk_mod.status()

    def stop_task(self, task_id: str):
        self._wk_mod.cancel(task_id)

    def list_database(self) -> list[ListItem]:
        return read_list_items(self._db_mod._database)

    def shutdown(self) -> None:
        """Cleanly aborts all running tasks and shuts down the thread pool."""
        logger.info("Shutting down Governor.")
        logger.info("Cancelling active tasks...")
        self._wk_mod.shutdown(True)
        logger.info("Cleaning up...")
        self._db_mod.shutdown(True)
        self._ep_mod.shutdown(True)
