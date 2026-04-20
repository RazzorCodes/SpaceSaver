import asyncio
import threading
import time
from enum import StrEnum
from typing import override

from activities.factory import ActivityFactory
from misc.logger import logger
from models.config import AppConfig
from modules.module import BusMessage, Module, Stage
from engine.executor import WorkExecutor, LightWorkExecutor, NetworkExecutor


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

        self.active_tasks: dict = {}
        self._tasks_lock = threading.Lock()
        
        self._shutdown_flag = threading.Event()
        self._drain_thread: threading.Thread | None = None
        
        self._response_buffer: list[tuple[list[str], bytes]] = []
        self._response_lock = threading.Lock()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._factory: ActivityFactory | None = None

        self._work_queue: asyncio.Queue = asyncio.Queue()
        self._light_queue: asyncio.Queue = asyncio.Queue()
        self._network_queue: asyncio.Queue = asyncio.Queue()

        self._work_executor: WorkExecutor | None = None
        self._light_executor: LightWorkExecutor | None = None
        self._network_executor: NetworkExecutor | None = None

    @override
    async def setup(self, config: AppConfig, db_mod=None) -> bool:
        logger.info("Setting up worker module")
        self._config = config
        self._db = db_mod._database if db_mod is not None else None
        
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error("WorkerModule must be set up within an asyncio loop")
            return False

        self._factory = ActivityFactory(
            config=self._config,
            db=self._db,
            response_callback=self._queue_response,
            active_tasks=self.active_tasks
        )

        self._work_executor = WorkExecutor(self._work_queue, max_workers=1)
        self._light_executor = LightWorkExecutor(self._light_queue, max_workers=1)
        self._network_executor = NetworkExecutor(self._network_queue, max_workers=5)

        self._work_executor.start()
        self._light_executor.start()
        self._network_executor.start()

        self._register_consumer(self._on_message, ["transcode"])
        self._register_consumer(self._on_message, ["scan"])
        self._register_consumer(self._on_message, ["list"])
        self._register_consumer(self._on_message, ["status"])
        self._register_consumer(self._on_cancel, ["cancel"])

        self.state = State.READY
        logger.info("Worker module ready")
        return True

    def _queue_response(self, labels: list[str], data: bytes) -> None:
        with self._response_lock:
            self._response_buffer.append((labels, data))

    def start_drain(self) -> None:
        self._drain_thread = threading.Thread(target=self._drain_loop, daemon=True, name="jackfield-drain")
        self._drain_thread.start()

    def _drain_loop(self) -> None:
        while not self._shutdown_flag.is_set():
            self._drain()
            
            with self._response_lock:
                current_responses = list(self._response_buffer)
                self._response_buffer.clear()
                
            for labels, data in current_responses:
                self._send(labels, data)
                
            time.sleep(0.005)

    def _on_message(self, msg: BusMessage) -> None:
        """Callback from Jackfield thread."""
        if self._loop is None:
            return
        
        labels = msg.get_labels()
        data = msg.get_bytes()
        
        self._loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._dispatch_message(labels, data))
        )

    async def _dispatch_message(self, labels: list[str], data: bytes) -> None:
        if not self._factory:
            return

        result = await self._factory.create(labels, data)
        if not result:
            return
        
        activity, task_id = result
        
        # Track activity
        with self._tasks_lock:
            self.active_tasks[task_id] = activity

        # Wrap activity to remove from active_tasks on completion
        original_run = activity.run
        async def wrapped_run():
            try:
                await original_run()
            finally:
                with self._tasks_lock:
                    self.active_tasks.pop(task_id, None)

        activity.run = wrapped_run

        # Route to appropriate queue
        if activity.type == "tran":
            await self._work_queue.put(activity)
        elif activity.type == "scan":
            await self._light_queue.put(activity)
        elif activity.type in ("list", "status"):
            await self._network_queue.put(activity)

    def _on_cancel(self, msg: BusMessage) -> None:
        task_id = msg.get_labels()[1]
        with self._tasks_lock:
            activity = self.active_tasks.pop(task_id, None)
        if activity is not None:
            activity.cancel()
            logger.info(f"Cancelled task {task_id}")
        else:
            logger.warning(f"Cancel requested for unknown task {task_id}")

    @override
    async def shutdown(self, force: bool) -> bool:
        self._shutdown_flag.set()
        
        with self._tasks_lock:
            tasks = list(self.active_tasks.values())
        for task in tasks:
            task.cancel()
        
        if self._loop:
            if self._work_executor:
                await self._work_executor.stop()
            if self._light_executor:
                await self._light_executor.stop()
            if self._network_executor:
                await self._network_executor.stop()
        
        return True
