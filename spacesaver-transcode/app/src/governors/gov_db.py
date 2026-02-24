from dataclasses import Field, dataclass
from enum import StrEnum

from app.src.data.db import Database
from app.src.governors.module import Module, Stage
from app.src.misc.logger import logger
from app.src.models.configuration import Configuration


class State(StrEnum):
    UNKNOWN = "unknown"
    # --- STARTUP ---
    STARTUP = "startup"

    RETRIEVING = "retrieving"
    CREATE = "creating (new)"
    CONNECT = "connecting"
    VALIDATE = "validating"
    MIGRATE = "migrating"
    READY = "ready"

    ERROR = "unrecoverable"

    def AsStage(self) -> Stage:
        match self:
            case self.UNKNOWN:
                return Stage.UNKNOWN
            case self.STARTUP:
                return Stage.STARTUP
            case self.RETRIEVING | self.CREATE | self.CONNECT | self.VALIDATE:
                return Stage.SETUP
            case self.MIGRATE:
                return Stage.PROCESSING
            case self.READY:
                return Stage.READY
            case self.ERROR | _:
                return Stage.ERROR  # default fallback


@dataclass
class DatabaseModule(Module):
    _database: Database | None = None
    _state: State = State.UNKNOWN
    _state_prev: State = State.UNKNOWN

    @property
    def state(self) -> State:
        return self._state

    @state.setter
    def state(self, value: State) -> None:
        logger.trace(f"state change :  [{self._state}]->[{value}]")
        self._state_prev = self._state
        self._state = value

    def setup(self) -> bool:
        state = State.RETRIEVING
        db = self._database

        if not db:
            state = State.ERROR
            return False

        if not db.exists:
            state = State.CREATE
            if not db.create():
                state = State.ERROR
                return False

        state = State.CONNECT
        if not db.connect():
            state = State.ERROR
            return False

        state = State.VALIDATE
        if not db.validate():
            if not db.migrate():
                state = State.ERROR
                return False

        state = State.READY
        return True
