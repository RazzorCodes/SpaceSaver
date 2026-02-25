from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Generic, Protocol, TypeVar, runtime_checkable

from misc.logger import logger
from models.configuration import Configuration


class Stage(StrEnum):
    UNKNOWN = "unknown"
    # --- startup ---
    STARTUP = "startup"
    SETUP = "setup"
    # --- work loop ---
    READY = "ready"
    PROCESSING = ""
    BLOCKED = "recoverable"
    # --- unrecoverable ---
    ERROR = "unrecoverable"


@runtime_checkable
class StagedEnum(Protocol):
    def AsStage(self) -> Stage: ...


T = TypeVar("T", bound=StagedEnum)


class Module(ABC, Generic[T]):
    def __init__(self, initial_state: T) -> None:
        self._state: T = initial_state
        self._state_prev: T = initial_state

    @property
    def state(self) -> T:
        return self._state

    @state.setter
    def state(self, value: T) -> None:
        logger.trace(
            f"{self.__class__.__name__} state change : {self._state.AsStage()} [{self._state}]->[{value}]"
        )
        self._state_prev = self._state
        self._state = value

    @abstractmethod
    def setup(self, config: Configuration) -> bool:
        raise NotImplementedError

    @staticmethod
    def setup_cb(result: bool, module: "Module") -> None:
        if result:
            logger.info(f"Success setting up {module.__class__.__name__}")
        else:
            logger.warning(f"Failure setting up {module.__class__.__name__}")

    @property
    def stage(self) -> Stage:
        return self._state.AsStage()
