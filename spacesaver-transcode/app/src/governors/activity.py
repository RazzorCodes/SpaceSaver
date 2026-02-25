from dataclasses import dataclass, field

from misc.logger import logger
from models.configuration import Configuration
from models.models import ListItem
from modules.module import Module, Stage, StagedEnum


@dataclass
class Activity:
    _modules: list[Module[StagedEnum]] = field(default_factory=list)

    def modules_valid(self) -> bool:
        for module in self._modules:
            logger.debug(
                f"{module.__class__.__name__} stage: {module.stage} state: {module.state}"
            )
            if module.stage == Stage.ERROR:
                return False
        return True

    def modules_ready(self) -> bool:
        for module in self._modules:
            logger.debug(
                f"{module.__class__.__name__} stage: {module.stage} state: {module.state}"
            )
            if module.stage not in [Stage.READY, Stage.PROCESSING, Stage.BLOCKED]:
                return False
        return True

    def _call(self, method, **kwargs):
        for module in self._modules:
            fn = getattr(module, method, None)
            if callable(fn):
                return fn(**kwargs)
