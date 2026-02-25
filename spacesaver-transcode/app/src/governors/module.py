from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Generic, Tuple, TypeVar, override

from misc.logger import logger
from models.configuration import Configuration


class Stage(StrEnum):
    UNKNOWN = "unknown"

    # --- startup ---
    STARTUP = "startup"

    SETUP = "setup"

    # --- work-in-progress ---
    RECOVERING_WORK = ""
    REMOVING_UNFINISHED_WORK = ""

    # --- work loop ---
    READY = "ready"
    # --- activities ---
    SCANNING = ""
    PROBING = ""
    PROCESSING = ""

    # --- unrecoverable ---
    ERROR = "unrecoverable failure"


T = TypeVar("T")


class State(ABC, Generic[T]):
    def __init__(self, value: T):
        self._value = value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, State):
            return self._value == other._value
        if isinstance(other, type(self._value)):
            return self._value == other
        return False

    def __hash__(self) -> int:
        return hash(self._value)

    def __str__(self) -> str:
        return self._value.__str__()

    @property
    def value(self) -> T:
        return self._value

    @abstractmethod
    def AsStage(self) -> Stage:
        raise NotImplementedError


class Module(ABC, Generic[T]):
    def __init__(self, initial_state: State[T]) -> None:
        self._state: State[T] = initial_state
        self._state_prev: State[T] = initial_state

    @property
    def state(self) -> State[T]:
        return self._state

    @state.setter
    def state(self, new: State[T]) -> None:
        logger.trace(
            f"{self.__class__.__name__} state change: "
            f"{self._state.AsStage()} [{self._state.value}] -> [{new.value}]"
        )
        self._state_prev = self._state
        self._state = new

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
        return self.state.AsStage()
