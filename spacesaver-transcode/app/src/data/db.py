import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, inspect
from sqlmodel import SQLModel, create_engine

from app.src.misc.logger import logger
from app.src.models.configuration import Configuration
from app.src.models.orm import ALL_TABLES


@dataclass
class Database:
    _db_path: Path
    _engine: Engine

    def __init__(self, config: Configuration):
        self._db_path = config.database_path

    @property
    def exists(self) -> bool:
        return self._db_path.exists()

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
                self._engine = create_engine(self._db_path.__str__())
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
        return True  # we do not support checks

    def migrate(self):
        return False  # or migrations for now
