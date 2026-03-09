import asyncio
from enum import StrEnum
from typing import override

from activities.list_activity import ListActivity
from activities.scan_activity import ScanActivity
from activities.status_activity import StatusActivity
from activities.transcode_activity import TranscodeActivity
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
from modules.module import Module, Stage
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
        self._app_host: str
        self._app_port: int
        self._serving: bool = False

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
            loop = asyncio.get_running_loop()
            future = loop.create_future()

            activity = ListActivity()
            activity.setup(
                db=self.module_bus["database"]._database, result_future=future
            )
            self.module_bus["worker"].submit(activity)

            # Wait for the worker thread to resolve the future
            try:
                return await asyncio.wait_for(future, timeout=30.0)
            except asyncio.TimeoutError:
                return JSONResponse(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    content={"message": "Request timed out"},
                )

        @self._app.get("/status")
        async def get_status():
            loop = asyncio.get_running_loop()
            future = loop.create_future()

            activity = StatusActivity()
            activity.setup(
                worker_module=self.module_bus["worker"], result_future=future
            )
            self.module_bus["worker"].submit(activity)

            return await future

        @self._app.put("/process/{hash}")
        async def process_hash(hash: str):
            return await self._start_transcode(hash)

        @self._app.delete("/cancel/{uuid}")
        async def cancel_task(uuid: str):
            success = self.module_bus["worker"].cancel(uuid)
            if success:
                return {"message": f"Task {uuid} cancelled"}
            else:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={"message": f"Task {uuid} not found"},
                )

        @self._app.put("/scan")
        async def start_scan():
            activity = ScanActivity()
            scan_path = self.module_bus["config"].media_path
            if not activity.setup(
                db=self.module_bus["database"]._database,
                path=scan_path,
                probe=True,
            ):
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"message": f"Failed to setup scan for {scan_path}"},
                )

            task_id = self.module_bus["worker"].submit(activity)
            return {"task": task_id}

        @self._app.get("/quality")
        def get_quality():
            cache_path = self.module_bus["config"].cache_path
            state = load_quality(cache_path)
            return state.model_dump()

        class QualityBody(BaseModel):
            preset: QualityPreset | None = None
            custom: QualitySettings | None = None

        @self._app.post("/quality")
        def set_quality(body: QualityBody):
            cache_path = self.module_bus["config"].cache_path

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

            save_quality(cache_path, state)
            logger.info(
                f"Quality updated: preset={state.active_preset}, crf={state.settings.crf}"
            )
            return state.model_dump()


    async def _start_transcode(
        self,
        hash: str,
        quality: QualitySettings | None = None,
    ):
        config: AppConfig = self.module_bus["config"]
        activity = TranscodeActivity()
        if not activity.setup(
            db=self.module_bus["database"]._database,
            hash=hash,
            quality=quality,
            cache_path=config.cache_path,
        ):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"message": f"Failed to setup transcode for {hash}"},
            )

        task_id = self.module_bus["worker"].submit(activity)
        return {"task": task_id}

    @override
    def setup(self, config: AppConfig, module_bus: dict | None = None) -> bool:
        logger.info("Setting up endpoint module")
        self._app_host = config.app_host
        self._app_port = config.app_port

        self.module_bus = module_bus or {}

        self.state = State.READY
        logger.info(
            "Endpoint module ready (waiting for server orchestration if applicable)."
        )
        return True

    @override
    def shutdown(self, force: bool) -> bool:
        """Cleanup specific endpoint module states."""
        logger.info("Shutting down Endpoint module...")
        self.state = State.UNKNOWN
        self._serving = False
        return True
