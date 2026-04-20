import threading

import jackfield

from misc.logger import logger
from models.config import AppConfig
from modules.database_module import DatabaseModule
from modules.endpoint_module import EndpointModule
from modules.worker_module import WorkerModule


class Governor:
    def __init__(self, config: AppConfig):
        self._config = config
        self._db_mod = DatabaseModule()
        self._wk_mod = WorkerModule()
        self._ep_mod = EndpointModule()
        self._ready = False

        for field_name in config.model_fields.keys():
            logger.debug(f"- {field_name} was set to: {getattr(config, field_name)}")

    @property
    def api_app(self):
        return self._ep_mod.api_app

    def start_endpoint(self) -> bool:
        if self._ready:
            self._ep_mod.expose()
            return True
        return False

    async def setup(self) -> None:
        """Initializes modules and wires them together via a shared message bus."""
        self._ready = True

        bus = jackfield.MessageBus()
        bus_lock = threading.Lock()
        for mod in (self._db_mod, self._wk_mod, self._ep_mod):
            mod.attach_bus(bus, bus_lock)

        self._ready &= await self._db_mod.setup(self._config)
        self._ready &= await self._wk_mod.setup(self._config, self._db_mod)
        self._ready &= await self._ep_mod.setup(self._config)

        if self._ready:
            self._wk_mod.start_drain()
            logger.info("Governor setup complete and ready.")
        else:
            logger.error("Governor setup failed.")

    @property
    def ready(self) -> bool:
        return self._ready

    async def shutdown(self) -> None:
        """Cleanly aborts all running tasks and shuts down the thread pool."""
        logger.info("Shutting down Governor")
        await self._wk_mod.shutdown(True)
        await self._db_mod.shutdown(True)
        await self._ep_mod.shutdown(True)
