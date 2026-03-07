from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import override

from data.db import Database
from misc.logger import logger
from models.configuration import Configuration
from models.models import ListItem
from models.orm import Items, Metadata, WorkItemStatus
from modules.module import Module, Stage, StagedEnum
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select


class State(StrEnum):
    UNKNOWN = "unknown"
    STARTUP = "startup"
    READY = "ready"
    ERROR = "unrecoverable"

    def AsStage(self) -> Stage:
        match self:
            case State.UNKNOWN:
                return Stage.UNKNOWN
            case State.STARTUP:
                return Stage.STARTUP
            # case State.RETRIEVING | State.CREATE | State.CONNECT | State.VALIDATE:
            #    return Stage.SETUP
            # case State.MIGRATE:
            #    return Stage.PROCESSING
            case State.READY:
                return Stage.READY
            case _:
                return Stage.ERROR


class EndpointModule(Module[State]):
    def __init__(self):
        super().__init__(State.UNKNOWN)

    @override
    def setup(self, config: Configuration) -> bool:
        logger.info("Setting up endpoint module")
        return self._setup()

    def _setup(self) -> bool:

        self.state = State.READY
        logger.info("Endpoint module ready")
        return True

    @override
    def shutdown(self, force: bool) -> bool:
        return True
