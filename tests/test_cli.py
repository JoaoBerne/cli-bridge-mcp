"""Human CLI: argument parsing + dispatch to the shared engine (with fakes, no real CLI)."""

import pytest

from cli_bridge import cli, server, telemetry
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    telemetry._reset_for_tests()
    # deterministic lane set — never touch the real PATH
    fake = LaneSpec("gemini", "Gemini", "echo", lambda *a: [])
    monkeypatch.setattr(server, "_active_lanes", lambda: ([fake], ""))
    yield
    telemetry._reset_for_tests()


def test_doctor(monkeypatch, capsys):
    monkeypatch.setattr(server, "_doctor", lambda host: "DOCTOR-OK")
    cli.main(["doctor"])
    assert "DOCTOR-OK" in capsys.readouterr().out


def test_ask(monkeypatch, capsys):
    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        assert lane.key == "gemini" and args["task"] == "hello world"
        return RunResult(True, "hi back", "ok", latency_ms=3)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)
    cli.main(["ask", "gemini", "hello", "world"])
    assert "hi back" in capsys.readouterr().out


def test_ask_unknown_lane_exits(monkeypatch):
    with pytest.raises(SystemExit):
        cli.main(["ask", "nope", "hi"])


def test_ask_all(monkeypatch, capsys):
    async def fake_body(lanes, args):
        return f"BODY:{args['task']}"
    monkeypatch.setattr(server, "_ask_all_body", fake_body)
    cli.main(["ask-all", "compare", "these"])
    assert "BODY:compare these" in capsys.readouterr().out


def test_ask_best(monkeypatch, capsys):
    async def fake_best(lanes, args):
        from mcp.types import TextContent
        return [TextContent(type="text", text=f"BEST:{args['mode']}")]
    monkeypatch.setattr(server, "_ask_best", fake_best)
    cli.main(["ask-best", "do", "x", "--mode", "fast"])
    assert "BEST:fast" in capsys.readouterr().out


def test_usage_json(capsys):
    cli.main(["usage", "--json"])
    out = capsys.readouterr().out
    import json
    assert "enabled" in json.loads(out)


def test_jobs(capsys):
    cli.main(["jobs"])
    out = capsys.readouterr().out
    assert "Async jobs" in out or "No async jobs" in out


def test_setup_write_creates_and_backs_up(tmp_path, capsys):
    target = tmp_path / "cfg.env"
    cli.main(["setup", "--write", str(target)])
    assert target.exists() and "CLI_BRIDGE_PROFILE" in target.read_text()
    # second write must back up the existing file, never silently overwrite
    cli.main(["setup", "--write", str(target)])
    assert (tmp_path / "cfg.env.bak").exists()


def test_init_prints_wiring(capsys):
    cli.main(["init"])
    out = capsys.readouterr().out
    assert "cli-bridge init" in out and "mcp add cli-bridge" in out and "CLI_BRIDGE_MOCK" in out


def test_bench(monkeypatch, capsys):
    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "answer", "ok", latency_ms=12)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)
    cli.main(["bench", "--lane", "gemini", "--prompt", "hi", "--runs", "3"])
    out = capsys.readouterr().out
    assert "bench gemini" in out and "ok 3/3" in out


def test_bench_unknown_lane_exits():
    with pytest.raises(SystemExit):
        cli.main(["bench", "--lane", "nope", "--prompt", "hi"])


def test_parser_wires_subcommands():
    p = cli.build_parser()
    a = p.parse_args(["review-diff", "--base", "main", "--json"])
    assert a.func is cli._cmd_review and a.base == "main" and a.json is True
    b = p.parse_args(["ask-best", "do", "it", "--mode", "deep"])
    assert b.func is cli._cmd_ask_best and b.mode == "deep" and b.task == ["do", "it"]


def test_review_diff_non_git_cwd_errors(tmp_path, monkeypatch, capsys):
    # point at a non-git dir so the path is deterministic (no real repo diff)
    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "[]", "ok", latency_ms=1)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)
    cli.main(["review-diff", "--cwd", str(tmp_path)])
    out = capsys.readouterr().out
    assert "[error]" in out or "empty diff" in out
