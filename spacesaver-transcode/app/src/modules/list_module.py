import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import override

import engine.classifier as classifier
import engine.hash as hasher
from data.db import Database
from misc.logger import logger
from models.configuration import Configuration
from modules.module import Module, Stage, StagedEnum


class State(StrEnum):
    UNKNOWN = "unknown"
    STARTUP = "startup"
    CHECK_PATH = "check-path"
    CHECK_PERM = "check-permissions"

    READY = "ready"

    LIST = "listing"

    UNREACHABLE = "recoverable"

    ERROR = "unrecoverable"

    def AsStage(self) -> Stage:
        match self:
            case State.UNKNOWN:
                return Stage.UNKNOWN
            case State.STARTUP:
                return Stage.STARTUP
            case State.CHECK_PATH | State.CHECK_PERM:
                return Stage.SETUP
            case State.LIST:
                return Stage.PROCESSING
            case State.READY:
                return Stage.READY
            case State.UNREACHABLE:
                return Stage.BLOCKED
            case _:
                return Stage.ERROR


class ListModule(Module[State]):
    def __init__(self):
        super().__init__(State.UNKNOWN)
        self._media_path = Path()

    @override
    def setup(self, config: Configuration) -> bool:
        logger.info("Setting up database module")
        return self._setup(media_path=config.media_path or None)

    def _setup(self, media_path: Path | None = None) -> bool:
        self.state = State.STARTUP

        self._media_path = media_path or self._media_path

        if not self._media_path:
            logger.critical("Invalid media path: empty")
            self.state = State.ERROR
            return False

        self.state = State.CHECK_PATH
        if not self._media_path.exists():
            logger.warning(
                f"{media_path} does not exist. Module will still try to query this path"
            )
            self.state = State.UNREACHABLE
            return False

        self.state = State.CHECK_PERM
        if not os.access(self._media_path, os.R_OK | os.W_OK):
            logger.critical(f"Incorrect permissions for {self._media_path}")
            self.state = State.UNREACHABLE
            return False

        self.state = State.READY
        return True

    def list_all(self):
        from models.models import ListItem

        if not os.path.isdir(self._media_path):
            logger.warning("[startup_flow] event=scan_dir_missing dir=%s", source_dir)
            return
        lst = []
        for root, _dirs, files in os.walk(self._media_path):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in [".mkv", ".mp4"]:
                    continue

                path = os.path.join(root, fname)
                name = classifier.clean_filename(fname)
                hash = hasher.compute_hash(path)
                lst.append(ListItem(name=name, path=path, hash=hash))
        return lst
