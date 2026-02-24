import pathlib
from dataclasses import Field, dataclass
from enum import StrEnum
from sqlite3 import Connection

from app.src.data.db import Database
from app.src.governors.gov_db import DatabaseModule
from app.src.governors.module import Module
from app.src.misc.logger import logger
from app.src.models.configuration import Configuration


@dataclass
class Governor:
    configuration: Configuration
    _modules: list[Module] | None = None

    def setup(self):
        if not self._modules or self._modules.count == 0:
            logger.critical("No modules available")
            return
        for module in self._modules:
            logger.info(f"Initializing {module.__class__.__name__}")
            if module.setup():
                logger.info(f"Success {module.__class__.__name__}")
            else:
                logger.warning(f"Faliure {module.__class__.__name__}")


gov = Governor(
    configuration=Configuration(database_path=pathlib.Path("./help/db.db")),
    _modules=[
        DatabaseModule(
            _database=Database(
                Configuration(database_path=pathlib.Path("./help/db.db"))
            )
        )
    ],
)

gov.setup()
