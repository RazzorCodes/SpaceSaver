from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import override

from data.db import Database
from governors.module import Module, Stage
from governors.module import State as ModuleState
from misc.logger import logger
from models.configuration import Configuration


class StateEnum(StrEnum):
    UNKNOWN = "unknown"
    # --- STARTUP ---
    STARTUP = "startup"
    RETRIEVING = "retrieving"
    CREATE = "creating"
    CONNECT = "connecting"
    VALIDATE = "validating"
    MIGRATE = "migrating"
    READY = "ready"
    ERROR = "unrecoverable"


class State(ModuleState[StateEnum]):
    def AsStage(self) -> Stage:
        match self._value:
            case StateEnum.UNKNOWN:
                return Stage.UNKNOWN
            case StateEnum.STARTUP:
                return Stage.STARTUP
            case (
                StateEnum.RETRIEVING
                | StateEnum.CREATE
                | StateEnum.CONNECT
                | StateEnum.VALIDATE
            ):
                return Stage.SETUP
            case StateEnum.MIGRATE:
                return Stage.PROCESSING
            case StateEnum.READY:
                return Stage.READY
            case _:
                return Stage.ERROR


class DatabaseModule(Module[StateEnum]):
    def __init__(self):
        self._state: State = State(StateEnum.UNKNOWN)
        self._state_prev: State = State(StateEnum.UNKNOWN)
        self._database: Database | None = None

    def _set_state(self, s: StateEnum) -> None:
        self.state = State(s)

    @override
    def setup(self, config: Configuration) -> bool:
        logger.info("Setting up database module")
        return self._setup(db_path=config.database_path or None)

    def _setup(
        self, db_path: Path | None = None, db_obj: Database | None = None
    ) -> bool:
        self._set_state(StateEnum.STARTUP)
        self._set_state(StateEnum.RETRIEVING)

        db = None
        if db_obj is not None:
            if db_path is not None:
                logger.debug("db_path ignored because db_obj was provided")
            logger.info(f"Setting up database module with provided database {db_obj}")
            db = db_obj
        elif db_path is not None:
            logger.info(f"Setting up database module from path {db_path}")
            try:
                db = Database(_db_path=db_path)
            except Exception as ex:
                logger.error(f"Could not retrieve database: {ex}")
        elif self._database:
            db = self._database

        if not db:
            self._set_state(StateEnum.ERROR)
            logger.error("Could not set up database module with empty database")
            return False

        if not db.exists:
            self._set_state(StateEnum.CREATE)
            if not db.create():
                self._set_state(StateEnum.ERROR)
                return False

        self._set_state(StateEnum.CONNECT)
        if not db.connect():
            self._set_state(StateEnum.ERROR)
            return False

        self._set_state(StateEnum.VALIDATE)
        if not db.validate():
            self._set_state(StateEnum.MIGRATE)
            if not db.migrate():
                self._set_state(StateEnum.ERROR)
                return False
            # Re-validate after migration to confirm it succeeded
            self._set_state(StateEnum.VALIDATE)
            if not db.validate():
                self._set_state(StateEnum.ERROR)
                return False

        self._set_state(StateEnum.READY)
        return True
