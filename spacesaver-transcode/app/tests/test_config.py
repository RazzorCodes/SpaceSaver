import os
from config import Config

def test_config_initialization():
    os.environ["TV_CRF"] = "12"
    cfg = Config()
    assert cfg.tv_crf == 12
    assert cfg.movie_res_cap == 2160 # Should default if missing

def test_config_update():
    cfg = Config()
    cfg.update({"tv_crf": 5, "rescan_interval": 30})
    assert cfg.tv_crf == 5
    assert cfg.rescan_interval == 30


test_config_initialization()
test_config_update()
print('Config tests passed!')
