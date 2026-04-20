import asyncio
from abc import ABC
from typing import Generic, TypeVar

from activities.activity import Activity
from misc.logger import logger

T = TypeVar("T", bound=Activity)


class BaseExecutor(ABC, Generic[T]):
    def __init__(self, name: str, queue: asyncio.Queue[T], max_workers: int = 1):
        self.name = name
        self.queue = queue
        self.max_workers = max_workers
        self._workers: list[asyncio.Task] = []
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        for i in range(self.max_workers):
            task = asyncio.create_task(self._worker_loop(i), name=f"{self.name}-worker-{i}")
            self._workers.append(task)
        logger.info(f"Executor {self.name} started with {self.max_workers} workers.")

    async def stop(self):
        self._running = False
        for task in self._workers:
            task.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info(f"Executor {self.name} stopped.")

    async def _worker_loop(self, worker_id: int):
        while self._running:
            try:
                activity = await self.queue.get()
                try:
                    logger.debug(f"[{self.name}-{worker_id}] Starting activity {activity.type}")
                    await activity.run()
                    logger.debug(f"[{self.name}-{worker_id}] Finished activity {activity.type}")
                except Exception as e:
                    logger.error(f"[{self.name}-{worker_id}] Activity {activity.type} failed: {e}")
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.name}-{worker_id}] Worker loop error: {e}")
                await asyncio.sleep(1)


class WorkExecutor(BaseExecutor):
    def __init__(self, queue: asyncio.Queue, max_workers: int = 1):
        super().__init__("WorkExecutor", queue, max_workers)


class LightWorkExecutor(BaseExecutor):
    def __init__(self, queue: asyncio.Queue, max_workers: int = 1):
        super().__init__("LightWorkExecutor", queue, max_workers)


class NetworkExecutor(BaseExecutor):
    def __init__(self, queue: asyncio.Queue, max_workers: int = 5):
        super().__init__("NetworkExecutor", queue, max_workers)
