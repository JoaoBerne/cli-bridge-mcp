"""Real end-to-end test: drive the server over stdio MCP as different hosts.

Proves the cross-host promise — "works in each CLI, for each CLI": when host X drives us,
lane X is hidden and the others are exposed. Uses a fake lane backed by `echo` so the test
needs no real AI CLI installed.
"""
import json
import os
import sys
import subprocess
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")


def _custom_lanes_file() -> str:
    """Two fake lanes whose binary is `echo` (always installed) so detection passes."""
    lanes = [
        {"key": "alpha", "display": "Alpha", "bin": "echo", "ask": ["{task}"],
         "client_ids": ["alpha-host"], "note": "fake"},
        {"key": "beta", "display": "Beta", "bin": "echo", "ask": ["{task}"],
         "client_ids": ["beta-host"], "note": "fake"},
    ]
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(lanes, fh)
    return path


def _rpc(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def _read_until_id(proc, want_id, limit=50):
    for _ in range(limit):
        line = proc.stdout.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("id") == want_id:
            return msg
    raise AssertionError(f"no response for id {want_id}")


def _list_tools_as_host(host_client_name: str, lanes_file: str) -> set[str]:
    env = dict(os.environ)
    env["CLI_BRIDGE_LANES_FILE"] = lanes_file
    # Restrict to our fake lanes only by also pointing real bins at a missing command,
    # so detection only keeps alpha/beta (echo). We just check alpha/beta visibility.
    proc = subprocess.Popen(
        [PY, "-m", "cli_bridge"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, env=env, cwd=ROOT,
    )
    try:
        _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": host_client_name, "version": "1.0"}}})
        _read_until_id(proc, 1)
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        resp = _read_until_id(proc, 2)
        return {t["name"] for t in resp["result"]["tools"]}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.skipif(not os.path.exists(PY), reason="venv python missing")
def test_alpha_host_hides_alpha_lane():
    lf = _custom_lanes_file()
    try:
        tools = _list_tools_as_host("alpha-host", lf)
        assert "ask_beta" in tools          # other lane exposed
        assert "ask_alpha" not in tools     # own lane hidden
        assert "doctor" in tools
    finally:
        os.remove(lf)


@pytest.mark.skipif(not os.path.exists(PY), reason="venv python missing")
def test_beta_host_hides_beta_lane():
    lf = _custom_lanes_file()
    try:
        tools = _list_tools_as_host("beta-host", lf)
        assert "ask_alpha" in tools
        assert "ask_beta" not in tools
    finally:
        os.remove(lf)


@pytest.mark.skipif(not os.path.exists(PY), reason="venv python missing")
def test_unknown_host_sees_all():
    lf = _custom_lanes_file()
    try:
        tools = _list_tools_as_host("some-other-client", lf)
        assert "ask_alpha" in tools and "ask_beta" in tools
    finally:
        os.remove(lf)
