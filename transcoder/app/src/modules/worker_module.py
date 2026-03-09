import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from typing import override

from activities.activity import Activity
from misc.logger import logger
from models.config import AppConfig
from modules.module import Module, Stage


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
        self.active_tasks: dict[str, Activity] = {}

    @override
    def setup(self, config: AppConfig) -> bool:
        logger.info("Setting up worker module")
        return self._setup()

    def submit(self, activity: Activity) -> str:
        task_id = f"{activity.type}_{uuid.uuid4().hex[:8]}"
        
        with self._tasks_lock:
            self.active_tasks[task_id] = activity
            
        if activity.type == "tran":
            self._work_executor.submit(self._run_activity, task_id, activity)
        elif activity.type == "scan":
            self._scan_executor.submit(self._run_activity, task_id, activity)
        else:
            # list, status — all go on the query executor
            self._query_executor.submit(self._run_activity, task_id, activity)

        return task_id

    def cancel(self, uuid: str) -> bool:
        with self._tasks_lock:
            activity = self.active_tasks.pop(uuid, None)
        if activity is None:
            return False
        activity.cancel()
        return True

    def status(self) -> dict[str, Activity]:
        with self._tasks_lock:
            return dict(self.active_tasks)

    def _run_activity(self, task_id: str, activity: Activity) -> None:
        """Wrapper to execute the activity and clean up memory when it finishes."""
        try:
            activity.run()
        except Exception as e:
            logger.error(f"Task {task_id} crashed: {e}")
        finally:
            # Remove the task from tracking once it finishes or crashes
            with self._tasks_lock:
                self.active_tasks.pop(task_id, None)

    def _setup(self) -> bool:

        self.state = State.READY
        logger.info("Worker module ready")
        return True

    @override
    def shutdown(self, force: bool) -> bool:
        with self._tasks_lock:
            tasks = list(self.active_tasks.values())
        for task in tasks:
            task.cancel()
        self._work_executor.shutdown(wait=False)
        self._query_executor.shutdown(wait=False)
        self._scan_executor.shutdown(wait=False)

        return True
