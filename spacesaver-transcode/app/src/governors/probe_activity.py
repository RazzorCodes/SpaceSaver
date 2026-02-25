from dataclasses import dataclass, field

from governors.activity import Activity
from misc.logger import logger
from models.configuration import Configuration
from models.models import ListItem
from modules.module import Module, Stage, StagedEnum


class ProbeActivity(Activity):
    _error: bool = False

    def __init__(self, _modules: list[Module[StagedEnum]]):
        super().__init__(_modules)

    def validate(self):
        if self._error:
            return False
        if not self.modules_valid():
            logger.critical("Modules are in unrecoverable state")
            self._error = True
            return False
        if not self.modules_ready():
            logger.warning("Not all modules are ready")
            return False

    def reset(self):
        self._error = False

    def loop(self):
        if self._error:
            return

        items: list[ListItem] = self._call("get_unknown")
        for item in items or []:
            item = self._call("probe", item=item)
            self._call("insert_record", record=item)
