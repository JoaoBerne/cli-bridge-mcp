"""Shared test isolation."""
import pytest


@pytest.fixture(autouse=True)
def _no_user_config_file(monkeypatch, tmp_path):
    """Point the JSON config file at a nonexistent path so a developer's real
    ~/.config/cli-bridge/config.json can never leak into (and flake) the tests."""
    monkeypatch.setenv("CLI_BRIDGE_CONFIG_FILE", str(tmp_path / "no-such-config.json"))
