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

    def setup(self) -> None:
        """Initializes the database and marks the Governor as ready."""
        self._ready = True
        self._ready &= self._db_mod.setup(self._config)
        self._ready &= self._wk_mod.setup(self._config)
        
        # Inject only the necessary references as a dictionary bus
        module_bus = {
            "worker": self._wk_mod,
            "database": self._db_mod,
            "config": self._config,
        }
        self._ready &= self._ep_mod.setup(self._config, module_bus=module_bus)
        if self._ready:
            logger.info("Governor setup complete and ready.")
        else:
            logger.error("Governor setup failed.")

    @property
    def ready(self) -> bool:
        return self._ready

    def shutdown(self) -> None:
        """Cleanly aborts all running tasks and shuts down the thread pool."""
        logger.info("Shutting down Governor")
        self._wk_mod.shutdown(True)
        self._db_mod.shutdown(True)
        self._ep_mod.shutdown(True)
