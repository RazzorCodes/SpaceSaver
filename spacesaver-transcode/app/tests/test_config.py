"""Tests for config.py."""

import os
from config import Config


def test_config_initialization():
    os.environ["TV_CRF"] = "12"
    cfg = Config()
    assert cfg.tv_crf == 12
    assert cfg.movie_res_cap == 2160  # Should default if missing


def test_config_update():
    cfg = Config()
    cfg.update({"tv_crf": 5})
    assert cfg.tv_crf == 5


def test_config_to_dict():
    cfg = Config()
    d = cfg.to_dict()
    assert "tv_crf" in d
    assert "movie_crf" in d
    assert "tv_res_cap" in d
    assert "movie_res_cap" in d
    # rescan_interval should no longer be in config
    assert "rescan_interval" not in d
