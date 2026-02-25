import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from misc.logger import logger
from models.configuration import Configuration
from modules.module import Module, Stage, StagedEnum


@dataclass
class Governor:
    configuration: Configuration
    _modules: list[Module[StagedEnum]] = field(default_factory=list)
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
        all_ready = True
        for module in self._modules:
            logger.info(
                f"{module.__class__.__name__} stage: {module.stage} state: {module.state}"
            )
            if module.stage != Stage.READY and module.stage != Stage.BLOCKED:
                all_ready = False
        return all_ready


if __name__ == "__main__":
    from governors.probe_activity import ProbeActivity
    from governors.scan_activity import ScanActivity
    from modules.database_module import DatabaseModule
    from modules.list_module import ListModule
    from modules.probe_module import ProbeModule

    db_mod = DatabaseModule()
    pb_mod = ProbeModule()
    ls_mod = ListModule()

    gov = Governor(Configuration(), _modules=[db_mod, pb_mod, ls_mod])
    pb_gov = ProbeActivity(_modules=[db_mod, pb_mod])
    sc_act = ScanActivity(_modules=[db_mod, ls_mod])
    gov.setup()

    passed = 0
    while not gov.ready() and not passed < 5:
        time.sleep(1)
        passed += 1
        logger.info("Waiting...")

    sc_act.loop()
    pb_gov.loop()
