import threading
import time
from enum import StrEnum
from typing import override

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from misc.logger import logger
from models.config import AppConfig
from modules.module import Module, Stage


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
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

        self._setup_routes()
        self._create_middleware()

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
        # --- GET ---
        # - GET - /version -
        # Returns the current app version
        @self._app.get("/version")
        def get_version():
            return {"version": 0}
            
        # - GET - /list - 
        # Returns all the known entries in the media folder
        def get_list():
            
            
        

    @override
    def setup(self, config: AppConfig) -> bool:
        logger.info("Setting up endpoint module")
        self._app_host = config.app_host
        self._app_port = config.app_port

        # 1. Configure Uvicorn
        uvi_config = uvicorn.Config(
            app=self._app, host=self._app_host, port=self._app_port, log_level="info"
        )
        self._server = uvicorn.Server(uvi_config)

        # 2. Spawn it in a daemon thread so it doesn't block exit
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

        self.state = State.READY
        logger.info(f"Endpoint thread running on {self._app_host}:{self._app_port}")
        return True

    @override
    def shutdown(self, force: bool) -> bool:
        """Gracefully stop the background server."""
        logger.info("Shutting down Endpoint module thread...")
        if self._server:
            # Tell the Uvicorn event loop to cleanly exit
            self._server.should_exit = True
        if self._thread:
            # Wait for the thread to actually finish
            self._thread.join(timeout=5.0)
        return True
