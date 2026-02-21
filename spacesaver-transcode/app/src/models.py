"""
models.py — Dataclasses and enums for SpaceSaver.
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MediaType(str, Enum):
    MOVIE = "movie"
    TV = "tv"


class FileStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"
    ALREADY_OPTIMAL = "already_optimal"


@dataclass
class MediaFile:
    uuid: str
    file_hash: str
    source_path: str
    dest_path: str
    media_type: MediaType
    clean_title: str
    year_or_episode: str
    status: FileStatus = FileStatus.PENDING
    progress: float = 0.0          # 0.0 – 100.0 (historic)
    frame_now: int = 0             # current frame tracker
    frame_total: int = 0           # total estimated frames
    error_count: int = 0
    error_msg: Optional[str] = None
    tv_crf: Optional[int] = None   # per-file override
    movie_crf: Optional[int] = None
    tv_res_cap: Optional[int] = None
    movie_res_cap: Optional[int] = None

    @staticmethod
    def new(
        file_hash: str,
        source_path: str,
        dest_path: str,
        media_type: MediaType,
        clean_title: str,
        year_or_episode: str,
    ) -> "MediaFile":
        return MediaFile(
            uuid=str(_uuid.uuid4()),
            file_hash=file_hash,
            source_path=source_path,
            dest_path=dest_path,
            media_type=media_type,
            clean_title=clean_title,
            year_or_episode=year_or_episode,
        )

    def to_dict(self, full: bool = False) -> dict:
        base = {
            "uuid": self.uuid,
            "name": f"{self.clean_title} {self.year_or_episode}".strip(),
            "status": self.status.value,
            "media_type": self.media_type.value,
            "progress": {
                "frame": {
                    "now": self.frame_now,
                    "total": self.frame_total
                }
            },
        }
        if full:
            base["file_hash"] = self.file_hash
            base["source_path"] = self.source_path
            base["dest_path"] = self.dest_path
            base["error_count"] = self.error_count
            base["error_msg"] = self.error_msg
            base["quality_overrides"] = {
                "tv_crf": self.tv_crf,
                "movie_crf": self.movie_crf,
                "tv_res_cap": self.tv_res_cap,
                "movie_res_cap": self.movie_res_cap,
            }
        return base
