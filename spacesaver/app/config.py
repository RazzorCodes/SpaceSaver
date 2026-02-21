"""
config.py — Global, live-mutable configuration loaded from environment variables.

Environment variables are injected from the Kubernetes ConfigMap via envFrom.
All settings can be updated at runtime via POST /config/quality without restarting.
"""

import os
import threading


class Config:
    """Mutable configuration object. Thread-safe via a read/write lock."""

    _lock = threading.RLock()

    def __init__(self) -> None:
        self._tv_crf: int = int(os.environ.get("TV_CRF", "18"))
        self._movie_crf: int = int(os.environ.get("MOVIE_CRF", "16"))
        self._tv_res_cap: int = int(os.environ.get("TV_RES_CAP", "1080"))
        self._movie_res_cap: int = int(os.environ.get("MOVIE_RES_CAP", "2160"))
        self._rescan_interval: int = int(os.environ.get("RESCAN_INTERVAL", "600"))

    # --- Getters ---

    @property
    def tv_crf(self) -> int:
        with self._lock:
            return self._tv_crf

    @property
    def movie_crf(self) -> int:
        with self._lock:
            return self._movie_crf

    @property
    def tv_res_cap(self) -> int:
        with self._lock:
            return self._tv_res_cap

    @property
    def movie_res_cap(self) -> int:
        with self._lock:
            return self._movie_res_cap

    @property
    def rescan_interval(self) -> int:
        with self._lock:
            return self._rescan_interval

    # --- Setters (for live update via API) ---

    def update(self, data: dict) -> None:
        with self._lock:
            if "tv_crf" in data:
                self._tv_crf = int(data["tv_crf"])
            if "movie_crf" in data:
                self._movie_crf = int(data["movie_crf"])
            if "tv_res_cap" in data:
                self._tv_res_cap = int(data["tv_res_cap"])
            if "movie_res_cap" in data:
                self._movie_res_cap = int(data["movie_res_cap"])
            if "rescan_interval" in data:
                self._rescan_interval = int(data["rescan_interval"])

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "tv_crf": self._tv_crf,
                "movie_crf": self._movie_crf,
                "tv_res_cap": self._tv_res_cap,
                "movie_res_cap": self._movie_res_cap,
                "rescan_interval": self._rescan_interval,
            }


# Singleton used across all modules
cfg = Config()
