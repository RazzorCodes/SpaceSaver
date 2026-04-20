import json
from pathlib import Path
from typing import Any, Callable

from activities.activity import Activity
from activities.list_activity import ListActivity
from activities.scan_activity import ScanActivity
from activities.status_activity import StatusActivity
from activities.transcode_activity import TranscodeActivity
from data.db import Database
from models.config import AppConfig


class ActivityFactory:
    def __init__(self, config: AppConfig, db: Database, response_callback: Callable[[list[str], bytes], None], active_tasks: dict[str, Activity]):
        self.config = config
        self.db = db
        self.response_callback = response_callback
        self.active_tasks = active_tasks

    async def create(self, labels: list[str], data: bytes) -> tuple[Activity, str] | None:
        if not labels:
            return None

        primary_label = labels[0]
        
        if primary_label == "transcode":
            task_id = labels[1]
            hash_val = labels[2]
            activity = TranscodeActivity()
            if await activity.setup(
                db=self.db,
                hash=hash_val,
                cache_path=self.config.cache_path,
            ):
                return activity, task_id
            
        elif primary_label == "scan":
            task_id = labels[1]
            params = json.loads(data)
            activity = ScanActivity()
            if await activity.setup(
                db=self.db,
                path=Path(params["path"]),
                probe=params.get("probe", False),
            ):
                return activity, task_id
            
        elif primary_label == "list":
            corr_id = labels[1]
            activity = ListActivity()
            if await activity.setup(
                db=self.db,
                corr_id=corr_id,
                response_callback=self.response_callback,
            ):
                return activity, corr_id
            
        elif primary_label == "status":
            corr_id = labels[1]
            activity = StatusActivity()
            if await activity.setup(
                active_tasks=self.active_tasks,
                corr_id=corr_id,
                response_callback=self.response_callback,
            ):
                return activity, corr_id
            
        return None
