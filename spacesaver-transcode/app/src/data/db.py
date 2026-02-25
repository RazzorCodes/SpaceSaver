import os
from dataclasses import dataclass, field
from pathlib import Path

from misc.logger import logger
from models.configuration import Configuration
from models.orm import ALL_TABLES
from sqlalchemy import Engine, inspect
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine


@dataclass
class Database:
    _db_path: Path  # = field(init=False)
    _engine: Engine | None = field(default=None)

    @property
    def exists(self) -> bool:
        logger.trace(
            f"Checking if database exists: {self._db_path} : {self._db_path.exists()}"
        )
        return self._db_path and self._db_path.exists()

    @property
    def engine(self) -> Engine | None:
        return self._engine

    def session(self) -> Session:
        return Session(self._engine)

    def create(self):
        if not self._db_path.parent.exists():
            logger.trace(f"Created parent folder for database: {self._db_path.parent}")
            os.makedirs(self._db_path.parent)
        try:
            sqlite_url = f"sqlite:///{self._db_path}"
            self._engine = create_engine(sqlite_url)
            SQLModel.metadata.create_all(self._engine)
        except Exception as Ex:
            logger.critical(f"Could not create engine: {Ex}")
            return False
        return True

    def connect(self):
        if not self._engine:
            try:
                sqlite_url = f"sqlite:///{self._db_path}"
                self._engine = create_engine(sqlite_url)
            except Exception as Ex:
                logger.critical(f"Could not create engine: {Ex}")
                return False

        try:
            _ = self._engine.connect()
        except Exception as Ex:
            logger.error(f"Could not connect to database engine: {Ex}")
            return False
        return True

    def validate(self):
        logger.debug(f"No validation is being done")
        return True  # we do not support checks

    def migrate(self):

        logger.debug(f"No migration is being done")
        return False  # or migrations for now
