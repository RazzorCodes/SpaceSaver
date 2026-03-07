import uuid
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from typing import override

from activities.activity import Activity
from misc.logger import logger
from models.configuration import Configuration
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
            # case State.RETRIEVING | State.CREATE | State.CONNECT | State.VALIDATE:
            #    return Stage.SETUP
            # case State.MIGRATE:
            #    return Stage.PROCESSING
            case State.READY:
                return Stage.READY
            case _:
                return Stage.ERROR


class WorkerModule(Module[State]):
    def __init__(self):
        super().__init__(State.UNKNOWN)

        self._query_executor = ThreadPoolExecutor(max_workers=1)
        self._work_executor = ThreadPoolExecutor(max_workers=1)
        self.active_tasks: dict[str, Activity] = {}

    @override
    def setup(self, config: Configuration) -> bool:
        logger.info("Setting up worker module")
        return self._setup()

    def submit(self, activity: Activity) -> str:
        task_id = f"{activity.type}_{uuid.uuid4().hex[:8]}"
        if activity.type == "tran":
            self._work_executor.submit(self._run_activity, task_id, activity)

        if activity.type == "scan":
            self._query_executor.submit(self._run_activity, task_id, activity)

        self.active_tasks[task_id] = activity
        return task_id

    def cancel(self, uuid: str) -> bool:
        if uuid not in self.active_tasks.keys():
            return False
        self.active_tasks[uuid].cancel()
        self.active_tasks.pop(uuid)
        return True

    def status(self):
        print(self.active_tasks)
        return self.active_tasks

    def _run_activity(self, task_id: str, activity: Activity) -> None:
        """Wrapper to execute the activity and clean up memory when it finishes."""
        try:
            activity.run()
        except Exception as e:
            logger.error(f"Task {task_id} crashed: {e}")
        finally:
            # Remove the task from tracking once it finishes or crashes
            self.active_tasks.pop(task_id, None)

    def _setup(self) -> bool:

        self.state = State.READY
        logger.info("Worker module ready")
        return True

    @override
    def shutdown(self, force: bool) -> bool:
        for task in self.active_tasks.values():
            task.cancel()
        self._work_executor.shutdown(wait=False)
        self._query_executor.shutdown(wait=False)

        return True
