from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class ListItem:
    id: int = field(default=0)
    hash: str = field(default="")
    name: str = field(default="")
    path: str = field(default="")
    status: str = field(default="unknown")
    size: int = field(default=0)
    resolution: Tuple[int, int] = field(default=(0, 0))
    duration: float = field(default=0.0)
    codec: str = field(default="")
    sar: str = field(default="")
    dar: str = field(default="")
    framerate: float = field(default=0.0)
    audio: list[str] = field(default_factory=list)
