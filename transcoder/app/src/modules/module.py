import threading
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, Callable, Generic, Protocol, TypeVar, runtime_checkable

from misc.logger import logger
from models.config import AppConfig


class Stage(StrEnum):
    UNKNOWN = "unknown"
    # --- startup ---
    STARTUP = "startup"
    SETUP = "setup"
    # --- work loop ---
    READY = "ready"
    PROCESSING = "processing"
    BLOCKED = "recoverable"
    # --- unrecoverable ---
    ERROR = "unrecoverable"


@runtime_checkable
class StagedEnum(Protocol):
    def AsStage(self) -> Stage: ...


T = TypeVar("T", bound=StagedEnum)


class BusMessage(Protocol):
    def get_labels(self) -> list[str]: ...
    def get_bytes(self) -> bytes: ...
    def get_uuid(self) -> str: ...


class Module(ABC, Generic[T]):
    def __init__(self, initial_state: T) -> None:
        self._state: T = initial_state
        self._state_prev: T = initial_state
        self._bus: Any = None

    def attach_bus(self, bus: Any, lock: threading.Lock) -> None:
        self._bus = bus
        self._bus_lock = lock

    def _send(self, labels: list[str], data: bytes = b"") -> None:
        import jackfield
        with self._bus_lock:
            self._bus.send(type(self).__name__.lower(), jackfield.Message(labels, data))

    def _register_consumer(self, callback: Callable[[BusMessage], None], labels: list[str]) -> None:
        import jackfield
        self._bus.register_consumer(callback, require=[jackfield.LabelDim.any_of(labels)])

    def _drain(self) -> None:
        with self._bus_lock:
            self._bus.drain()

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
    def setup(self, config: AppConfig) -> bool:
        pass

    @abstractmethod
    def shutdown(self, force: bool) -> bool:
        pass

    @property
    def stage(self) -> Stage:
        return self._state.AsStage()
