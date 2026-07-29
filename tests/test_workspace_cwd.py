"""Default delegate cwd: the host's MCP workspace root instead of whatever we were launched in.

Precedence, and the whole point of this file: caller's `cwd` > CLI_BRIDGE_DEFAULT_CWD >
first existing MCP root > the inherited cwd (the historical behaviour, still the fallback).
"""
import asyncio
import pathlib
from types import SimpleNamespace

import pytest

from cli_bridge import mcp_compat, server
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "state.sqlite"))
    monkeypatch.delenv("CLI_BRIDGE_DEFAULT_CWD", raising=False)
    monkeypatch.setattr(server, "_workspace_cache", None)   # memoized per process, not per test


class _Session:
    """Just enough ServerSession to answer (or refuse) a roots/list."""

    def __init__(self, roots=(), *, capable=True, raises=None):
        self._roots, self._raises, self.calls = roots, raises, 0
        self.client_params = SimpleNamespace(
            capabilities=SimpleNamespace(roots=SimpleNamespace() if capable else None))

    async def list_roots(self):
        self.calls += 1
        if self._raises:
            raise self._raises
        return SimpleNamespace(roots=[SimpleNamespace(uri=u) for u in self._roots])


def _with_ctx(session):
    """Install a fake request context the way mcp 2.x does. On 1.x server.request_context raises
    LookupError outside a request, so request_ctx() falls through to this same var — one fake
    exercises the real lookup on both majors."""
    return mcp_compat._CTX.set(SimpleNamespace(session=session, meta=None))


def _lane():
    return LaneSpec("gpt", "GPT", "echo", lambda *a: ["x"], caps=frozenset({"model", "agent"}))


def _spawn_cwd(monkeypatch, args):
    """Run a delegation with the spawn faked out; return the cwd the child would have gotten."""
    seen = {}

    async def fake_spawn(argv, timeout, expanded, env, **kw):
        seen["cwd"] = expanded
        return RunResult(True, "ok", "ok")

    monkeypatch.setattr(server, "_spawn_with_retry", fake_spawn)
    res = asyncio.run(server._run_lane(_lane(), args))
    return seen.get("cwd"), res


# ── no host to ask: the historical behaviour, unchanged ───────────────────────────────────────

def test_no_request_context_keeps_the_inherited_cwd(monkeypatch):
    # Human CLI, async jobs, tests: nobody to ask, so don't invent a directory.
    assert asyncio.run(server._workspace_root()) == ""
    cwd, res = _spawn_cwd(monkeypatch, {"task": "hi"})
    assert cwd is None and res.ok


def test_host_without_roots_capability_is_never_asked(monkeypatch):
    session = _Session(capable=False)
    token = _with_ctx(session)
    try:
        cwd, _ = _spawn_cwd(monkeypatch, {"task": "hi"})
    finally:
        mcp_compat._CTX.reset(token)
    assert cwd is None
    assert session.calls == 0          # no wasted round-trip on every single delegation


def test_list_roots_failure_never_breaks_a_delegation(monkeypatch):
    token = _with_ctx(_Session(raises=RuntimeError("no back-channel")))
    try:
        cwd, res = _spawn_cwd(monkeypatch, {"task": "hi"})
    finally:
        mcp_compat._CTX.reset(token)
    assert cwd is None and res.ok


# ── the host answers ──────────────────────────────────────────────────────────────────────────

def test_first_usable_root_becomes_the_default_cwd(tmp_path, monkeypatch):
    token = _with_ctx(_Session([tmp_path.as_uri()]))
    try:
        cwd, _ = _spawn_cwd(monkeypatch, {"task": "hi"})
    finally:
        mcp_compat._CTX.reset(token)
    assert cwd == str(tmp_path)


def test_unusable_roots_are_skipped(tmp_path, monkeypatch):
    gone = tmp_path / "deleted"
    token = _with_ctx(_Session(["https://example.com/repo",           # not a file:// root
                                gone.as_uri(),                         # does not exist
                                tmp_path.as_uri()]))
    try:
        cwd, _ = _spawn_cwd(monkeypatch, {"task": "hi"})
    finally:
        mcp_compat._CTX.reset(token)
    assert cwd == str(tmp_path)


def test_no_usable_root_falls_back_to_the_inherited_cwd(monkeypatch):
    token = _with_ctx(_Session([]))
    try:
        cwd, _ = _spawn_cwd(monkeypatch, {"task": "hi"})
    finally:
        mcp_compat._CTX.reset(token)
    assert cwd is None


def test_roots_are_asked_once_per_process(tmp_path, monkeypatch):
    session = _Session([tmp_path.as_uri()])
    token = _with_ctx(session)
    try:
        _spawn_cwd(monkeypatch, {"task": "one"})
        cwd, _ = _spawn_cwd(monkeypatch, {"task": "two"})
    finally:
        mcp_compat._CTX.reset(token)
    assert cwd == str(tmp_path)
    assert session.calls == 1


# ── precedence ────────────────────────────────────────────────────────────────────────────────

def test_caller_cwd_wins_over_the_workspace_root(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    session = _Session([tmp_path.as_uri()])
    token = _with_ctx(session)
    try:
        cwd, _ = _spawn_cwd(monkeypatch, {"task": "hi", "cwd": str(explicit)})
    finally:
        mcp_compat._CTX.reset(token)
    assert cwd == str(explicit)
    assert session.calls == 0


def test_a_bad_caller_cwd_still_fails_with_the_same_message(tmp_path, monkeypatch):
    token = _with_ctx(_Session([tmp_path.as_uri()]))
    try:
        _, res = _spawn_cwd(monkeypatch, {"task": "hi", "cwd": str(tmp_path / "nope")})
    finally:
        mcp_compat._CTX.reset(token)
    assert not res.ok and "is not an existing directory" in res.output


def test_env_default_wins_over_the_workspace_root(tmp_path, monkeypatch):
    forced = tmp_path / "forced"
    forced.mkdir()
    monkeypatch.setenv("CLI_BRIDGE_DEFAULT_CWD", str(forced))
    session = _Session([tmp_path.as_uri()])
    token = _with_ctx(session)
    try:
        cwd, _ = _spawn_cwd(monkeypatch, {"task": "hi"})
    finally:
        mcp_compat._CTX.reset(token)
    assert cwd == str(forced)
    assert session.calls == 0


def test_env_default_pointing_nowhere_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_DEFAULT_CWD", str(tmp_path / "nope"))
    cwd, res = _spawn_cwd(monkeypatch, {"task": "hi"})
    assert cwd is None and res.ok      # a misconfigured env var must not kill every delegation


# ── uri parsing ───────────────────────────────────────────────────────────────────────────────

def test_root_uri_parsing(tmp_path):
    spaced = tmp_path / "with space"
    spaced.mkdir()
    assert server._path_from_root_uri(spaced.as_uri()) == str(spaced)     # %20 decoded
    assert server._path_from_root_uri("https://example.com/x") == ""
    assert server._path_from_root_uri("not a uri at all") == ""
    assert server._path_from_root_uri(pathlib.Path.home().as_uri()) == str(pathlib.Path.home())
