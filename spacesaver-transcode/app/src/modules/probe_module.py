from enum import StrEnum
from pathlib import Path
from typing import override

import engine.probe as probe
from misc.logger import logger
from models.configuration import Configuration
from models.models import ListItem
from modules.module import Module, Stage, StagedEnum


class State(StrEnum):
    UNKNOWN = "unknown"
    STARTUP = "startup"
    PRE_CHECK = "pre-check"
    READY = "ready"
    PROBING = "probing"
    PROBE_SUCCESS = "probe-success"
    ERROR = "unrecoverable"

    def AsStage(self) -> Stage:
        match self:
            case State.UNKNOWN:
                return Stage.UNKNOWN
            case State.STARTUP:
                return Stage.STARTUP
            case State.PRE_CHECK:
                return Stage.SETUP
            case State.PROBING | State.PROBE_SUCCESS:
                return Stage.PROCESSING
            case State.READY:
                return Stage.READY
            case _:
                return Stage.ERROR


class ProbeModule(Module[State]):
    def __init__(self):
        super().__init__(State.UNKNOWN)

    @override
    def setup(self, config: Configuration) -> bool:
        logger.info("Setting up probe module")
        return self._setup()

    def _setup(self) -> bool:
        self.state = State.STARTUP
        self.state = State.PRE_CHECK

        if not probe.check_executable():
            logger.error("ffprobe executable not found")
            self.state = State.ERROR
            return False

        self.state = State.READY
        return True

    def probe(self, item: ListItem) -> ListItem:
        # 1. call classifier
        item = probe.inspect(item)
        return item
