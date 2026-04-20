import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable, override

from activities.activity import Activity
from data.db import Database
from data.db_op import read_list_items
from misc.logger import logger


@dataclass
class ListActivity(Activity):
    db: Database | None = None
    corr_id: str | None = None
    response_callback: Callable[[list[str], bytes], None] | None = None

    @property
    @override
    def type(self) -> str:
        return "list"

    @property
    def valid(self) -> bool:
        return self.db is not None and self.corr_id is not None and self.response_callback is not None

    @override
    async def setup(self, db: Database, corr_id: str, response_callback: Callable[[list[str], bytes], None]) -> bool:
        self.db = db
        self.corr_id = corr_id
        self.response_callback = response_callback
        return True

    @override
    async def run(self) -> None:
        if not self.valid:
            logger.error("ListActivity invalid")
            return

        try:
            items = await asyncio.to_thread(read_list_items, self.db)
            serialized = [asdict(item) for item in items]
            data = json.dumps(serialized).encode()
        except Exception as e:
            logger.error(f"List query failed: {e}")
            data = json.dumps({"__error__": str(e)}).encode()

        if self.response_callback and self.corr_id:
            self.response_callback(["response", self.corr_id], data)

    @override
    def cancel(self) -> None:
        pass

    @override
    def result(self) -> Any:
        return None
