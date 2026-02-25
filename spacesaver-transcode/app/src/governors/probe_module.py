from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import override

import engine.probe as probe
from data.db import Database
from governors.module import Module, Stage
from misc.logger import logger
from models.configuration import Configuration


class State(StrEnum):
    UNKNOWN = "unknown"

    STARTUP = "startup"

    PRE_CHECK = "pre-check"
    # PROBE_CHECK = "probe-check"

    READY = "ready"

    PROBING = "probing"
    PROBE_SUCCESS = "probe-success"

    ERROR = "unrecoverable"

    def AsStage(self) -> Stage:
        match self:
            case self.UNKNOWN:
                return Stage.UNKNOWN
            case self.STARTUP:
                return Stage.STARTUP
            case self.PRE_CHECK:
                return Stage.SETUP
            case self.PROBING | self.PROBE_SUCCESS:
                return Stage.PROCESSING
            case self.READY:
                return Stage.READY
            case self.ERROR | _:
                return Stage.ERROR  # default fallback


@dataclass
class ProbeModule(Module):
    _state: State = State.UNKNOWN
    _state_prev: State = State.UNKNOWN

    @property
    def state(self) -> State:
        return self._state

    @state.setter
    def state(self, value: State) -> None:
        logger.trace(
            f"{self.__class__.__name__} state change : {self._state.AsStage()} [{self._state}]->[{value}]"
        )
        self._state_prev = self._state
        self._state = value

    @override
    def setup(self, config: Configuration) -> bool:
        logger.info(f"Setting up database module")
        return self._setup()

    def _setup(
        self,
    ) -> bool:
        self.state = State.STARTUP

        self.state = State.PRE_CHECK
        if not probe.check_executable():
            logger.error("ffprobe executable not found")
            self.state = State.ERROR
            return False

        self.state = State.READY
        return True
