import json
from dataclasses import dataclass
from typing import Any, Callable, override

from activities.activity import Activity
from misc.logger import logger


@dataclass
class StatusActivity(Activity):
    active_tasks: dict[str, Activity] | None = None
    corr_id: str | None = None
    response_callback: Callable[[list[str], bytes], None] | None = None

    @property
    @override
    def type(self) -> str:
        return "status"

    @property
    def valid(self) -> bool:
        return self.active_tasks is not None and self.corr_id is not None and self.response_callback is not None

    @override
    async def setup(self, active_tasks: dict[str, Activity], corr_id: str, response_callback: Callable[[list[str], bytes], None]) -> bool:
        self.active_tasks = active_tasks
        self.corr_id = corr_id
        self.response_callback = response_callback
        return True

    @override
    async def run(self) -> None:
        if not self.valid:
            logger.error("StatusActivity invalid")
            return

        try:
            result: dict = {}
            assert self.active_tasks is not None
            for task_id, act in self.active_tasks.items():
                entry: dict = {"type": act.type}
                if act.type == "tran":
                    # We need to access progress info. 
                    # Since these are now objects, we can just read them.
                    entry["progress"] = {
                        "percent": getattr(act, "progress_percent", 0),
                        "current_frame": getattr(act, "progress_current_frame", 0),
                        "total_frames": getattr(act, "progress_total_frames", 0),
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

        if self.response_callback and self.corr_id:
            self.response_callback(["response", self.corr_id], data)

    @override
    def cancel(self) -> None:
        pass

    @override
    def result(self) -> Any:
        return None
