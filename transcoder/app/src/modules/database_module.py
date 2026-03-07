from dataclasses import field
from enum import StrEnum
from pathlib import Path
from typing import override

from data.db import Database
from misc.logger import logger
from models.configuration import Configuration
from modules.module import Module, Stage


class State(StrEnum):
    UNKNOWN = "unknown"
    STARTUP = "startup"
    RETRIEVING = "retrieving"
    CREATE = "creating"
    CONNECT = "connecting"
    VALIDATE = "validating"
    MIGRATE = "migrating"
    READY = "ready"
    ERROR = "unrecoverable"

    def AsStage(self) -> Stage:
        match self:
            case State.UNKNOWN:
                return Stage.UNKNOWN
            case State.STARTUP:
                return Stage.STARTUP
            case State.RETRIEVING | State.CREATE | State.CONNECT | State.VALIDATE:
                return Stage.SETUP
            case State.MIGRATE:
                return Stage.PROCESSING
            case State.READY:
                return Stage.READY
            case _:
                return Stage.ERROR


class DatabaseModule(Module[State]):
    _database: Database = field(init=False)

    def __init__(self):
        super().__init__(State.UNKNOWN)

    @override
    def setup(self, config: Configuration) -> bool:
        logger.info("Setting up database module")
        return self._setup(db_path=config.database_path or None)

    def _setup(
        self, db_path: Path | None = None, db_obj: Database | None = None
    ) -> bool:
        self.state = State.STARTUP
        self.state = State.RETRIEVING

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
                return False
        elif self._database:
            db = self._database
        else:
            self.state = State.ERROR
            logger.error("Could not set up database module with empty database")
            return False

        if not db.exists:
            self.state = State.CREATE
            if not db.create():
                self.state = State.ERROR
                return False

        self.state = State.CONNECT
        if not db.connect():
            self.state = State.ERROR
            return False

        self.state = State.VALIDATE
        if not db.validate():
            self.state = State.MIGRATE
            if not db.migrate():
                self.state = State.ERROR
                return False
            self.state = State.VALIDATE
            if not db.validate():
                self.state = State.ERROR
                return False

        self._database = db
        self.state = State.READY
        logger.info("Database module ready")
        return True

    @override
    def shutdown(self, force: bool) -> bool:
        self._database.close(force)
        return True
