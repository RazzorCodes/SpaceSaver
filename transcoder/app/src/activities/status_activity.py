import asyncio
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from activities.activity import Activity
from misc.logger import logger

# Avoid circular imports at runtime
if TYPE_CHECKING:
    from modules.worker_module import WorkerModule


@dataclass
class StatusActivity(Activity):
    worker_module: "WorkerModule | None" = None
    result_future: asyncio.Future | None = None
    _abort_flag: threading.Event = field(default_factory=threading.Event)

    @property
    @override
    def type(self) -> str:
        return "status"

    @property
    def valid(self) -> bool:
        return bool(self.worker_module is not None and self.result_future is not None)

    def setup(self, worker_module: "WorkerModule", result_future: asyncio.Future) -> bool:
        self.worker_module = worker_module
        self.result_future = result_future
        self._abort_flag.clear()
        return True

    def run(self) -> None:
        if not self.valid:
            logger.error("Status activity invalid: Missing worker module or future")
            if self.result_future and not self.result_future.done(): # type: ignore
                future = self.result_future
                future.get_loop().call_soon_threadsafe( # type: ignore
                    future.set_exception, RuntimeError("Invalid Setup") # type: ignore
                )
            return

        logger.info("Starting Status query")
        try:
            assert self.worker_module is not None
            # Get the status directly from the worker module bus
            tasks = self.worker_module.status()
            
            # Serialize - filter out ephemeral query activities (status, list)
            result = {}
            for task_id, act in tasks.items():
                if act.type in ("status", "list"):
                    continue
                entry: dict = {"type": act.type}
                # Include live progress for transcode activities
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
            
            if not self._abort_flag.is_set() and self.result_future and not self.result_future.done(): # type: ignore
                future = self.result_future
                future.get_loop().call_soon_threadsafe( # type: ignore
                    future.set_result, result # type: ignore
                )
        except Exception as e:
            logger.error(f"Status activity failed: {e}")
            if self.result_future and not self.result_future.done(): # type: ignore
                future = self.result_future
                future.get_loop().call_soon_threadsafe( # type: ignore
                    future.set_exception, e # type: ignore
                )

    def cancel(self) -> None:
        """Triggers the abort flag"""
        logger.info("Cancel requested. Stopping status activity...")
        self._abort_flag.set()
        if self.result_future and not self.result_future.done(): # type: ignore
            future = self.result_future
            future.get_loop().call_soon_threadsafe( # type: ignore
                future.set_exception, asyncio.CancelledError() # type: ignore
            )

    def result(self):
        return None
