"""Isolation guarantee: running a delegate must not write into the user's CLI config dirs.

The whole project promise is "spawn the official CLI, touch nothing of the user's own setup".
This test runs a fake lane (echo) through the real _run_lane path and asserts none of the
known CLI config directories changed (mtime snapshot). The terse preamble is prepended to the
spawned process's argv only — never written to disk.
"""
import asyncio
import os

from cli_bridge import lanes, server

_CLI_DIRS = [
    os.path.expanduser("~/.gemini"),
    os.path.expanduser("~/.codex"),
    os.path.expanduser("~/.vibe"),
    os.path.expanduser("~/.config/opencode"),
    os.path.expanduser("~/.claude"),
]


def _snapshot(dirs):
    snap = {}
    for d in dirs:
        for root, _, files in os.walk(d):
            for f in files:
                p = os.path.join(root, f)
                try:
                    snap[p] = os.stat(p).st_mtime_ns
                except OSError:
                    pass
    return snap


def test_delegate_run_does_not_touch_cli_config_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("CLI_BRIDGE_OVERFLOW_DIR", str(tmp_path / "overflow"))
    existing = [d for d in _CLI_DIRS if os.path.isdir(d)]
    before = _snapshot(existing)

    # fake lane backed by `echo` (always installed) — exercises the full _run_lane path,
    # including the terse preamble, without needing a real AI CLI.
    fake = lanes.LaneSpec("xtest", "X", "echo", lambda task, m, e, a, b="": [task])
    res = asyncio.run(server._run_lane(fake, {"task": "hello world"}))
    assert res.ok

    after = _snapshot(existing)
    changed = [p for p in after if before.get(p) != after[p]]
    new = [p for p in after if p not in before]
    assert not changed, f"delegate run modified CLI config files: {changed[:5]}"
    assert not new, f"delegate run created CLI config files: {new[:5]}"
