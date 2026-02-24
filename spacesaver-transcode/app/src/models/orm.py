from enum import StrEnum
from typing import Tuple

from sqlalchemy import Column
from sqlalchemy.orm import declared_attr
from sqlalchemy.types import JSON
from sqlmodel import Field, Relationship, SQLModel, String, TypeDecorator


class WorkItemStatus(StrEnum):
    # --- not assigned ---
    UNKNOWN = "unknown"
    # --- assigned, not actively worked on ---
    PENDING = "pending"
    # --- in progress ---
    PROCESSING = "processing"
    # --- end state ---
    DONE = "done"  # processed
    OPTIMAL = "optimal"  # already optimal
    ERROR = "error"  # failed


class ResolutionDecorator(TypeDecorator[tuple[int, int]]):
    impl = String
    cache_ok = True

    def __init__(self, separator: str = "x", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.separator = separator

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return f"{value[0]}{self.separator}{value[1]}"

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        w, h = value.split(self.separator, 1)
        return int(w), int(h)


class Items(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    path: str
    status: WorkItemStatus = Field(default=WorkItemStatus.UNKNOWN)

    # Reverse relationship to Metadata
    metadata_item: "Metadata" = Relationship(back_populates="item")


class Metadata(SQLModel, table=True):
    id: int = Field(primary_key=True, foreign_key="items.id", default=-1)

    # --- file info ---
    size: int = Field(default=-1)

    # --- media info ---
    duration: float
    # --- video ---
    codec: str
    resolution: tuple[int, int] = Field(sa_type=ResolutionDecorator)
    sar: str
    dar: str
    framerate: float
    # --- audio ---
    audio: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    # --- database ---
    item: "Items" = Relationship(back_populates="metadata_item")


ALL_TABLES = [
    Items,
    Metadata,
]
