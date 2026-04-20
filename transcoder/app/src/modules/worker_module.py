import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from enum import StrEnum
from typing import override

from activities.scan_activity import ScanActivity
from activities.transcode_activity import TranscodeActivity
from data.db_op import read_list_items
from misc.logger import logger
from models.config import AppConfig
from modules.module import BusMessage, Module, Stage


class State(StrEnum):
    UNKNOWN = "unknown"
    STARTUP = "startup"
    READY = "ready"
    ERROR = "unrecoverable"

    def AsStage(self) -> Stage:
        match self:
            case State.UNKNOWN:
                return Stage.UNKNOWN
            case State.STARTUP:
                return Stage.STARTUP
            case State.READY:
                return Stage.READY
            case _:
                return Stage.ERROR


class WorkerModule(Module[State]):
    def __init__(self):
        super().__init__(State.UNKNOWN)

        self._query_executor = ThreadPoolExecutor(max_workers=1)
        self._work_executor = ThreadPoolExecutor(max_workers=1)
        self._scan_executor = ThreadPoolExecutor(max_workers=1)
        self._tasks_lock = threading.Lock()
        self.active_tasks: dict = {}
        self._shutdown_flag = threading.Event()
        self._drain_thread: threading.Thread | None = None
        self._response_buffer: list[tuple[list[str], bytes]] = []

    @override
    def setup(self, config: AppConfig, db_mod=None) -> bool:
        logger.info("Setting up worker module")
        self._config = config
        self._db = db_mod._database if db_mod is not None else None

        self._register_consumer(self._on_transcode, ["transcode"])
        self._register_consumer(self._on_scan, ["scan"])
        self._register_consumer(self._on_cancel, ["cancel"])
        self._register_consumer(self._on_list, ["list"])
        self._register_consumer(self._on_status, ["status"])

        self.state = State.READY
        logger.info("Worker module ready")
        return True

    def start_drain(self) -> None:
        self._drain_thread = threading.Thread(target=self._drain_loop, daemon=True, name="jackfield-drain")
        self._drain_thread.start()

    def _drain_loop(self) -> None:
        while not self._shutdown_flag.is_set():
            self._drain()
            # Send responses buffered during drain (can't call send() inside drain() — would re-borrow the bus)
            for labels, data in self._response_buffer:
                self._send(labels, data)
            self._response_buffer.clear()
            time.sleep(0.005)

    def _on_transcode(self, msg: BusMessage) -> None:
        labels = msg.get_labels()
        task_id = labels[1]
        hash_val = labels[2]

        activity = TranscodeActivity()
        if not activity.setup(
            db=self._db,
            hash=hash_val,
            quality=None,
            cache_path=self._config.cache_path,
        ):
            logger.error(f"Failed to set up transcode activity for {hash_val}")
            return

        with self._tasks_lock:
            self.active_tasks[task_id] = activity
        self._work_executor.submit(self._run_activity, task_id, activity)

    def _on_scan(self, msg: BusMessage) -> None:
        labels = msg.get_labels()
        task_id = labels[1]
        params = json.loads(msg.get_bytes())

        from pathlib import Path
        activity = ScanActivity()
        if not activity.setup(
            db=self._db,
            path=Path(params["path"]),
            probe=params.get("probe", False),
        ):
            logger.error(f"Failed to set up scan activity for {params['path']}")
            return

        with self._tasks_lock:
            self.active_tasks[task_id] = activity
        self._scan_executor.submit(self._run_activity, task_id, activity)

    def _on_cancel(self, msg: BusMessage) -> None:
        task_id = msg.get_labels()[1]
        with self._tasks_lock:
            activity = self.active_tasks.pop(task_id, None)
        if activity is not None:
            activity.cancel()
            logger.info(f"Cancelled task {task_id}")
        else:
            logger.warning(f"Cancel requested for unknown task {task_id}")

    def _on_list(self, msg: BusMessage) -> None:
        corr_id = msg.get_labels()[1]
        try:
            items = read_list_items(self._db)
            serialized = [asdict(item) for item in items]
            data = json.dumps(serialized).encode()
        except Exception as e:
            logger.error(f"List query failed: {e}")
            data = json.dumps({"__error__": str(e)}).encode()
        self._response_buffer.append((["response", corr_id], data))

    def _on_status(self, msg: BusMessage) -> None:
        corr_id = msg.get_labels()[1]
        try:
            tasks = self.status()
            result: dict = {}
            for task_id, act in tasks.items():
                entry: dict = {"type": act.type}
                if act.type == "tran":
                    entry["progress"] = {
                        "percent": act.progress_percent,
                        "current_frame": act.progress_current_frame,
                        "total_frames": act.progress_total_frames,
                    }
                    if hasattr(act, "_record") and act._record:
                        entry["name"] = act._record.name
                    if hasattr(act, "quality_preset"):
                        entry["quality_preset"] = act.quality_preset
                elif act.type == "scan":
                    entry["name"] = "Library Scan"
                result[task_id] = entry
            data = json.dumps(result).encode()
        except Exception as e:
            logger.error(f"Status query failed: {e}")
            data = json.dumps({"__error__": str(e)}).encode()
        self._response_buffer.append((["response", corr_id], data))

    def status(self) -> dict:
        with self._tasks_lock:
            return dict(self.active_tasks)

    def _run_activity(self, task_id: str, activity) -> None:
        try:
            activity.run()
        except Exception as e:
            logger.error(f"Task {task_id} crashed: {e}")
        finally:
            with self._tasks_lock:
                self.active_tasks.pop(task_id, None)

    @override
    def shutdown(self, force: bool) -> bool:
        self._shutdown_flag.set()
        with self._tasks_lock:
            tasks = list(self.active_tasks.values())
        for task in tasks:
            task.cancel()
        self._work_executor.shutdown(wait=False)
        self._query_executor.shutdown(wait=False)
        self._scan_executor.shutdown(wait=False)
        return True
