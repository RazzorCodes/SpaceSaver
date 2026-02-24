from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DATABASE_PATH = "/media/.transcode/database.db"


@dataclass
class Configuration:
    database_path: Path = field(default_factory=lambda: Path(DEFAULT_DATABASE_PATH))
