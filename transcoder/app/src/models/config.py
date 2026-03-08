from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    media_path: Path = Path("/media")
    cache_path: Path = Path("/cache")

    db_path: Path = Path("/storage/spacesaver-transcode/main.db")

    model_config = SettingsConfigDict(env_file="../.env")
