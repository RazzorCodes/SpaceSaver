from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DATABASE_PATH = "~/.local/spacesaver-transcode/database.db"
DEFAULT_MEDIA_PATH = "~/Videos"


@dataclass
class Configuration:
    database_path: Path = field(
        default_factory=lambda: Path(DEFAULT_DATABASE_PATH).expanduser()
    )
    media_path: Path = field(
        default_factory=lambda: Path(DEFAULT_MEDIA_PATH).expanduser()
    )
