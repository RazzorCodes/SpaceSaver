import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from governors.module import Module, Stage
from misc.logger import logger
from models.configuration import Configuration


@dataclass
class Governor:
    configuration: Configuration
    _modules: list[Module] = field(default_factory=list)
    _executor: ThreadPoolExecutor = field(init=False)

    def __post_init__(self):
        self._executor = ThreadPoolExecutor(max_workers=len(self._modules) or 1)

    def setup(self) -> None:
        if not self._modules:
            logger.warning("No modules available to set up")
            return

        futures = {
            self._executor.submit(module.setup, self.configuration): module
            for module in self._modules
        }

        for future in as_completed(futures):
            module = futures[future]
            try:
                result = future.result()
            except Exception as ex:
                logger.error(f"{module.__class__.__name__} raised during setup: {ex}")
                result = False
            Module.setup_cb(result, module)

        self._executor.shutdown(wait=False)

    def ready(self) -> bool:
        for module in self._modules:
            logger.debug(
                f"{module.__class__.__name__} stage: {module.stage} state: {module.state}"
            )
            if module.stage != Stage.READY:
                logger.debug(f"Module {module.__class__.__name__} not ready")
                return False
        return True


if __name__ == "__main__":
    from governors.database_module import DatabaseModule
    from governors.probe_module import ProbeModule

    gov = Governor(Configuration(), _modules=[DatabaseModule(), ProbeModule()])
    gov.setup()

    passed = 0
    while not gov.ready() and passed < 5:
        time.sleep(1)
        passed += 1
        logger.info("Waiting...")
