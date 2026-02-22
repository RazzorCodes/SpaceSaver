"""
models.py — Dataclasses and enums for SpaceSaver (database-first architecture).

Three normalised tables: entries, metadata, progress.
"""

from __future__ import annotations

import json
import uuid as _uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


# ── Enums ────────────────────────────────────────────────────────────────────

class FileStatus(str, Enum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    OPTIMUM = "optimum"
    DONE = "done"


class MetadataKind(str, Enum):
    DECLARED = "declared"
    ACTUAL = "actual"


# ── Sentinel ─────────────────────────────────────────────────────────────────

UNKNOWN_SENTINEL = "Unknown"


# ── Core dataclasses ─────────────────────────────────────────────────────────

@dataclass
class Entry:
    """Core identity row in the `entries` table."""
    uuid: str
    name: str
    hash: str
    path: str
    size: int

    @staticmethod
    def new(name: str, hash: str, path: str, size: int) -> Entry:
        return Entry(
            uuid=str(_uuid.uuid4()),
            name=name,
            hash=hash,
            path=path,
            size=size,
        )

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "hash": self.hash,
            "path": self.path,
            "size": self.size,
        }


@dataclass
class Metadata:
    """Stream properties row in the `metadata` table (FK → entries.uuid)."""
    uuid: str
    kind: MetadataKind
    codec: str = UNKNOWN_SENTINEL
    format: str = UNKNOWN_SENTINEL
    sar: str = UNKNOWN_SENTINEL
    dar: str = UNKNOWN_SENTINEL
    resolution: str = UNKNOWN_SENTINEL
    framerate: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "kind": self.kind.value,
            "codec": self.codec,
            "format": self.format,
            "sar": self.sar,
            "dar": self.dar,
            "resolution": self.resolution,
            "framerate": self.framerate,
            "extra": self.extra,
        }


@dataclass
class Progress:
    """Transcoding state row in the `progress` table (FK → entries.uuid)."""
    uuid: str
    status: FileStatus = FileStatus.PENDING
    progress: float = 0.0
    frame_current: int = 0
    frame_total: int = 0
    workfile: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "status": self.status.value,
            "progress": self.progress,
            "frame_current": self.frame_current,
            "frame_total": self.frame_total,
            "workfile": self.workfile,
        }


# ── Classifier output ────────────────────────────────────────────────────────

@dataclass
class DeclaredMetadata:
    """
    Output of the classifier — one per file.

    Every field defaults to the Unknown sentinel. A field parse failure must not
    affect other fields. No field is ever None.
    """
    codec: str = UNKNOWN_SENTINEL
    format: str = UNKNOWN_SENTINEL
    sar: str = UNKNOWN_SENTINEL
    dar: str = UNKNOWN_SENTINEL
    resolution: str = UNKNOWN_SENTINEL
    framerate: str = UNKNOWN_SENTINEL

    @property
    def parsed_field_count(self) -> int:
        """Number of fields that were successfully parsed (not Unknown)."""
        all_fields = [self.codec, self.format, self.sar, self.dar,
                      self.resolution, self.framerate]
        return sum(1 for v in all_fields if v != UNKNOWN_SENTINEL)

    @property
    def unknown_field_count(self) -> int:
        return 6 - self.parsed_field_count

    def to_metadata(self, uuid: str) -> Metadata:
        """Convert to a Metadata row with kind=DECLARED."""
        return Metadata(
            uuid=uuid,
            kind=MetadataKind.DECLARED,
            codec=self.codec,
            format=self.format,
            sar=self.sar,
            dar=self.dar,
            resolution=self.resolution,
            framerate=float(self.framerate) if self.framerate != UNKNOWN_SENTINEL else 0.0,
        )
