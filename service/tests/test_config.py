from pathlib import Path

import pytest

from tablo import config
from tablo.config import ConfigError

CONFIG_YAML = Path(__file__).resolve().parents[1] / "config.yaml"


def test_dev_config_loads():
    cfg = config.load(CONFIG_YAML, local=False)
    assert [b.id for b in cfg.buttons] == list(range(1, 8))
    assert cfg.button(3).tile_entity == "light.desk_lamp"
    assert cfg.button(1).tile_entity is None  # "all off" never fills its tile
    assert cfg.button(7).long.action == "qr"
    assert cfg.display.semester_start.isoformat() == "2026-09-01"


def test_button_8_is_not_configurable():
    with pytest.raises(ConfigError, match="fixed"):
        config.from_dict({"buttons": [{"id": 8, "short": {"action": "event"}}]})


def test_toggle_needs_entity():
    with pytest.raises(ConfigError, match="needs an entity"):
        config.from_dict({"buttons": [{"id": 2, "short": {"action": "toggle"}}]})


def test_theme_is_dark_unless_set():
    assert config.from_dict({}).display.theme == "dark"
    assert config.from_dict({"display": {"theme": "light"}}).display.theme == "light"
    with pytest.raises(ConfigError, match="theme"):
        config.from_dict({"display": {"theme": "sepia"}})


def test_unknown_keys_are_rejected():
    with pytest.raises(ConfigError, match="unknown"):
        config.from_dict({"buttons": [{"id": 2, "colour": "red"}]})


def test_env_overrides_tokens(monkeypatch):
    monkeypatch.setenv("TABLO_DEVICE_TOKEN", "from-env")
    assert config.from_dict({"device": {"token": "from-file"}}).device_token == "from-env"
