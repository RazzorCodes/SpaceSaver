import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from activities.scan_activity import ScanActivity
from activities.transcode_activity import TranscodeActivity
from misc.logger import logger
from models.configuration import Configuration
from modules.database_module import DatabaseModule
from modules.module import Module, Stage, StagedEnum


class Governor:
    _config: Configuration
    _db_mod: DatabaseModule = DatabaseModule()
    _ready: bool = False

    def __init__(self, config: Configuration):
        self._config = config

        self.scan_act = ScanActivity()
        self.tran_act = TranscodeActivity()

    def _setup_modules(self) -> None:
        self._ready &= self._db_mod.setup(self._config)

    def _setup_activities(self) -> None:
        self.scan_act.setup(self._db_mod._database, self._config.media_path, True)
        self.tran_act.setup(
            self._db_mod._database,
            "d4767a8e822f85875bc70ef6c7fcb8921083a4e15b810ad7ed9f86a175eb56d7",
        )

    def setup(self):
        self._setup_modules()
        self._setup_activities()

    def run(self) -> None:
        self.scan_act.run()
        self.tran_act.run()

    @property
    def ready(self) -> bool:
        return self._ready


if __name__ == "__main__":
    gov = Governor(
        Configuration(database_path="./main.db", media_path="/home/andrei/Videos")
    )
    gov.setup()
    gov.run()
