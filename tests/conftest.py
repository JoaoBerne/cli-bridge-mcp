"""Shared test isolation."""
import datetime as _dt

import pytest

# Lane cost/routing tests assert on the DEFAULT cost tiers (free/limited/paid). A lane with a
# vendor-announced `sunset` date degrades free→limited once that date passes (lanes.py), so the
# suite would otherwise start failing on the calendar day a built-in lane's free tier dies (e.g.
# Gemini, 2026-06-18) — a wall-clock time-bomb, not a real regression. Freeze `date.today()` to a
# fixed reference BEFORE any current sunset so the mechanism tests are deterministic. The sunset
# behaviour itself is covered explicitly in test_lanes (which injects `today=`), unaffected by this.
_FROZEN_TODAY = _dt.date(2026, 6, 1)


class _FrozenDate(_dt.date):
    @classmethod
    def today(cls):
        return _FROZEN_TODAY


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    # `lanes.sunset_passed` does `from datetime import date` INSIDE the call, so it resolves this
    # patched attribute at call time. datetime.datetime.now() / time.time() are untouched.
    monkeypatch.setattr(_dt, "date", _FrozenDate)


@pytest.fixture(autouse=True)
def _no_user_config_file(monkeypatch, tmp_path):
    """Point the JSON config file at a nonexistent path so a developer's real
    ~/.config/cli-bridge/config.json can never leak into (and flake) the tests."""
    monkeypatch.setenv("CLI_BRIDGE_CONFIG_FILE", str(tmp_path / "no-such-config.json"))
