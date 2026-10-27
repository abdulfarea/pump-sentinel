import pytest

from pump_sentinel.config import ConfigError, load_config

MINT = "So11111111111111111111111111111111111111112"


def write(tmp_path, extra="", base=None):
    path = tmp_path / "config.toml"
    path.write_text(base if base is not None else f'mints = ["{MINT}"]\n' + extra)
    return path


def test_config_resolves_relative_paths(tmp_path):
    config = load_config(write(tmp_path))
    assert config["interval_seconds"] == 60
    assert config["state_path"] == str(tmp_path / "data/sentinel.sqlite3")
    assert config["wallet"] == ""


@pytest.mark.parametrize("extra", ["interval_seconds = 0\n", "interval_seconds = nan\n",
                                   "max_cycles = true\n", "secret_key = 'NOT_A_REAL_KEY'\n",
                                   "max_history = 1\n", "wallet = 'suhail777'\n"])
def test_rejects_invalid_config(tmp_path, extra):
    with pytest.raises(ValueError):
        load_config(write(tmp_path, extra))


def test_requires_mint_not_alias(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, base="mints = []\n"))


def test_duplicate_mints_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, base=f'mints = ["{MINT}", "{MINT}"]\n'))


def test_policy_is_checked(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "[policy]\nmax_slot_skew = -1\n"))
