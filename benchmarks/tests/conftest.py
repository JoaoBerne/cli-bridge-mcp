"""Eval-harness tests, run standalone: `pytest benchmarks/tests` (not in the main suite's testpaths)."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))   # so `import eval` finds eval.py


@pytest.fixture(autouse=True)
def _no_user_config_file(monkeypatch, tmp_path):
    """Point the JSON config file at a nonexistent path so a developer's real
    ~/.config/cli-bridge/config.json can never leak into (and flake) the tests."""
    monkeypatch.setenv("CLI_BRIDGE_CONFIG_FILE", str(tmp_path / "no-such-config.json"))
