import asyncio
import json
import threading
import uuid
from enum import StrEnum
from typing import override

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from misc.logger import logger
from models.config import AppConfig
from models.quality import (
    PRESETS,
    QualityPreset,
    QualitySettings,
    QualityState,
    load_quality,
    save_quality,
)
from modules.module import BusMessage, Module, Stage
from pydantic import BaseModel


class State(StrEnum):
    UNKNOWN = "unknown"
    STARTUP = "startup"
    READY = "ready"
    SERVING = "serving"
    ERROR = "unrecoverable"

    def AsStage(self) -> Stage:
        match self:
            case State.UNKNOWN:
                return Stage.UNKNOWN
            case State.STARTUP:
                return Stage.STARTUP
            case State.SERVING:
                return Stage.PROCESSING
            case State.READY:
                return Stage.READY
            case _:
                return Stage.ERROR


class EndpointModule(Module[State]):
    def __init__(self):
        super().__init__(State.UNKNOWN)
        self._serving: bool = False
        self._pending: dict[str, asyncio.Future] = {}
        self._pending_lock = threading.Lock()

        self._app = FastAPI()
        self._setup_routes()
        self._create_middleware()

    @property
    def api_app(self) -> FastAPI:
        return self._app

    def expose(self):
        self._serving = True
        self.state = State.SERVING
        logger.info("Endpoint module is now SERVING requests.")

    def _create_middleware(self):
        @self._app.middleware("http")
        async def check_readiness(request: Request, call_next):
            if not self._serving:
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={"message": "System is starting up. Please wait..."},
                )
            return await call_next(request)

    def _on_response(self, msg: BusMessage) -> None:
        corr_id = msg.get_labels()[1]
        with self._pending_lock:
            future = self._pending.pop(corr_id, None)
        if future is None or future.done():
            return
        payload = json.loads(msg.get_bytes())
        if isinstance(payload, dict) and "__error__" in payload:
            future.get_loop().call_soon_threadsafe(
                future.set_exception, RuntimeError(payload["__error__"])
            )
        else:
            future.get_loop().call_soon_threadsafe(future.set_result, payload)

    async def _query(self, label: str) -> object:
        corr_id = uuid.uuid4().hex[:8]
        future = asyncio.get_running_loop().create_future()
        with self._pending_lock:
            self._pending[corr_id] = future
        self._send([label, corr_id])
        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            with self._pending_lock:
                self._pending.pop(corr_id, None)
            raise

    def _setup_routes(self):
        @self._app.get("/version")
        def get_version():
            try:
                with open("version.txt", "r") as f:
                    return {"version": f.read().strip()}
            except Exception:
                return {"version": "unknown"}

        @self._app.get("/list")
        async def get_list():
            try:
                return await self._query("list")
            except asyncio.TimeoutError:
                return JSONResponse(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    content={"message": "Request timed out"},
                )

        @self._app.get("/status")
        async def get_status():
            return await self._query("status")

        @self._app.put("/process/{hash}")
        async def process_hash(hash: str):
            return self._start_transcode(hash)

        @self._app.delete("/cancel/{task_uuid}")
        async def cancel_task(task_uuid: str):
            self._send(["cancel", task_uuid])
            return {"message": f"Cancel requested for task {task_uuid}"}

        @self._app.put("/scan")
        async def start_scan():
            task_id = f"scan_{uuid.uuid4().hex[:8]}"
            params = json.dumps({
                "path": str(self._config.media_path),
                "probe": True,
            }).encode()
            self._send(["scan", task_id], params)
            return {"task": task_id}

        @self._app.get("/quality")
        def get_quality():
            state = load_quality(self._config.cache_path)
            return state.model_dump()

        class QualityBody(BaseModel):
            preset: QualityPreset | None = None
            custom: QualitySettings | None = None

        @self._app.post("/quality")
        def set_quality(body: QualityBody):
            if body.preset and body.custom:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "message": "Specify either 'preset' or 'custom', not both."
                    },
                )
            if not body.preset and not body.custom:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"message": "Specify either 'preset' or 'custom'."},
                )

            if body.preset:
                state = QualityState(
                    active_preset=body.preset,
                    settings=PRESETS[body.preset].model_copy(),
                )
            else:
                state = QualityState(
                    active_preset=None,
                    settings=body.custom,  # type: ignore[arg-type]
                )

            save_quality(self._config.cache_path, state)
            logger.info(
                f"Quality updated: preset={state.active_preset}, crf={state.settings.crf}"
            )
            return state.model_dump()

    def _start_transcode(self, hash: str) -> dict:
        task_id = f"tran_{uuid.uuid4().hex[:8]}"
        self._send(["transcode", task_id, hash])
        return {"task": task_id}

    @override
    def setup(self, config: AppConfig) -> bool:
        logger.info("Setting up endpoint module")
        self._config = config
        self._register_consumer(self._on_response, ["response"])
        self.state = State.READY
        logger.info(
            "Endpoint module ready (waiting for server orchestration if applicable)."
        )
        return True

    @override
    def shutdown(self, force: bool) -> bool:
        logger.info("Shutting down Endpoint module...")
        self.state = State.UNKNOWN
        self._serving = False
        with self._pending_lock:
            for future in self._pending.values():
                if not future.done():
                    future.get_loop().call_soon_threadsafe(
                        future.set_exception, asyncio.CancelledError()
                    )
            self._pending.clear()
        return True
