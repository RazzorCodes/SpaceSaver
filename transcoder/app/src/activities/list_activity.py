import asyncio
import threading
from dataclasses import asdict, dataclass, field
from typing import override

from activities.activity import Activity
from data.db import Database
from data.db_op import read_list_items
from misc.logger import logger


@dataclass
class ListActivity(Activity):
    db: Database | None = None
    result_future: asyncio.Future | None = None
    _abort_flag: threading.Event = field(default_factory=threading.Event)

    @property
    @override
    def type(self) -> str:
        return "list"

    @property
    def valid(self) -> bool:
        return bool(self.db is not None and self.result_future is not None)

    def setup(self, db: Database, result_future: asyncio.Future) -> bool:
        self.db = db
        self.result_future = result_future
        self._abort_flag.clear()
        return True

    def run(self) -> None:
        if not self.valid:
            logger.error("List activity invalid: Missing database or future")
            if self.result_future and not self.result_future.done(): # type: ignore
                future = self.result_future
                future.get_loop().call_soon_threadsafe( # type: ignore
                    future.set_exception, RuntimeError("Invalid Setup") # type: ignore
                )
            return

        logger.info("Starting List query")
        try:
            assert self.db is not None
            items = read_list_items(self.db)
            # Convert dataclass list to dicts so FastAPI can JSON-serialize them
            serialized = [asdict(item) for item in items]
            if not self._abort_flag.is_set() and self.result_future and not self.result_future.done(): # type: ignore
                future = self.result_future
                future.get_loop().call_soon_threadsafe( # type: ignore
                    future.set_result, serialized # type: ignore
                )
        except Exception as e:
            logger.error(f"List activity failed: {e}")
            if self.result_future and not self.result_future.done(): # type: ignore
                future = self.result_future
                future.get_loop().call_soon_threadsafe( # type: ignore
                    future.set_exception, e # type: ignore
                )

    def cancel(self) -> None:
        """Triggers the abort flag"""
        logger.info("Cancel requested. Stopping list activity...")
        self._abort_flag.set()
        if self.result_future and not self.result_future.done(): # type: ignore
            future = self.result_future
            future.get_loop().call_soon_threadsafe( # type: ignore
                future.set_exception, asyncio.CancelledError() # type: ignore
            )

    def result(self):
        return None
