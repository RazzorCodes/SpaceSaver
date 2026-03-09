from dataclasses import dataclass, field
from pathlib import Path

from misc.logger import logger
from sqlalchemy import Engine, event
from sqlmodel import Session, SQLModel, create_engine


# --- SQLite Performance & Concurrency Hooks ---
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Forces SQLite into WAL mode every time a connection is opened.
    This allows simultaneous reading (FastAPI) and writing (Transcoder).
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


@dataclass
class Database:
    _db_path: Path | str  # Updated type hint to show it accepts string before post_init
    _engine: Engine | None = field(default=None)

    def __post_init__(self):
        if isinstance(self._db_path, str):
            self._db_path = Path(self._db_path)

    @property
    def exists(self) -> bool:
        # Note: If you run this in Docker (Python 3.12), remove follow_symlinks=True!
        logger.trace(
            f"Checking if database exists: {self._db_path} : {self._db_path.exists()}"
        )
        return bool(self._db_path and self._db_path.exists())

    @property
    def engine(self) -> Engine | None:
        return self._engine

    def session(self) -> Session:
        if self._engine is None:
            raise RuntimeError("Database engine not initialized. Call create() or connect() first.")
        return Session(self._engine)

    def create(self):
        if not self._db_path.parent.exists():
            logger.trace(f"Created parent folder for database: {self._db_path.parent}")
            # Cleaner pathlib way to make directories:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            sqlite_url = f"sqlite:///{self._db_path}"
            # ADDED: check_same_thread=False
            self._engine = create_engine(
                sqlite_url, connect_args={"check_same_thread": False}
            )
            SQLModel.metadata.create_all(self._engine)
        except Exception as Ex:
            logger.critical(f"Could not create engine: {Ex}")
            return False
        return True

    def connect(self):
        if not self._engine:
            try:
                sqlite_url = f"sqlite:///{self._db_path}"
                # ADDED: check_same_thread=False
                self._engine = create_engine(
                    sqlite_url, connect_args={"check_same_thread": False}
                )
            except Exception as Ex:
                logger.critical(f"Could not create engine: {Ex}")
                return False

        try:
            # Note: We assign to a throwaway variable to ensure the connection actually succeeds
            with self._engine.connect() as _:
                pass
        except Exception as Ex:
            logger.error(f"Could not connect to database engine: {Ex}")
            return False
        return True

    def validate(self):
        logger.debug("No validation is being done")
        return True  # we do not support checks

    def migrate(self):
        logger.debug("No migration is being done")
        return False  # or migrations for now

    def close(self, force: bool):
        if self._engine:
            self._engine.dispose()
