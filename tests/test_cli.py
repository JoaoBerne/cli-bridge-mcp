"""Human CLI: argument parsing + dispatch to the shared engine (with fakes, no real CLI)."""

import json

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


def test_build_dispatches_isolated(monkeypatch, capsys):
    async def fake_build(lane, args, run_lane, architect=None):
        assert lane.key == "gemini" and args["task"] == "add a version flag"
        assert architect is None
        return "ISOLATED-DIFF-REPORT"
    monkeypatch.setattr(cli.worktrees, "ask_build_isolated", fake_build)
    cli.main(["build", "gemini", "add", "a", "version", "flag"])
    assert "ISOLATED-DIFF-REPORT" in capsys.readouterr().out


def test_build_unknown_lane_exits():
    with pytest.raises(SystemExit):
        cli.main(["build", "nope", "do", "x"])


def test_build_unknown_architect_exits():
    with pytest.raises(SystemExit):                      # lane resolves, architect does not
        cli.main(["build", "gemini", "do", "x", "--architect", "nope"])


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


def test_bench_all_table(monkeypatch, capsys):
    a = LaneSpec("a", "A", "echo", lambda *x: [])
    b = LaneSpec("b", "B", "echo", lambda *x: [])
    monkeypatch.setattr(server, "_active_lanes", lambda: ([a, b], ""))

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "x", "ok", latency_ms=7)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)
    cli.main(["bench", "--all", "--prompt", "hi", "--runs", "2"])
    out = capsys.readouterr().out
    assert "| lane |" in out and "| a |" in out and "| b |" in out


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


def test_eval_offline_self_check_passes(capsys):
    # default (no --live): runs the deterministic scorer over the shipped corpus, exits 0
    with pytest.raises(SystemExit) as e:
        cli.main(["eval"])
    assert e.value.code == 0
    assert "calibration: PASS" in capsys.readouterr().out


def test_eval_live_runs_both_arms(monkeypatch, capsys):
    pool = [LaneSpec(k, k.upper(), "echo", lambda *a: [])
            for k in ("gemini", "gpt", "mistral", "opencode")]
    monkeypatch.setattr(server, "_active_lanes", lambda: (pool, ""))

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "[]", "ok", latency_ms=1)   # wiring only; no real findings
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)
    cli.main(["eval", "--live", "--council-lanes", "gemini,gpt,mistral,opencode",
              "--single-lane", "gpt", "--k", "4", "--repeats", "1", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["tool"] == "eval" and data["k"] == 4 and data["single_lane"] == "gpt"


def test_set_cost_persists_to_config_file(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("CLI_BRIDGE_CONFIG_FILE", str(cfg))
    monkeypatch.delenv("CLI_BRIDGE_OLLAMA_COST", raising=False)
    cli.main(["set-cost", "ollama", "limited", "--note", "slow on this machine"])
    out = capsys.readouterr().out
    assert "persisted" in out
    data = json.loads(cfg.read_text())
    assert data["lanes"]["ollama"] == {"cost": "limited", "cost_note": "slow on this machine"}


def test_set_cost_warns_when_env_shadows(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLI_BRIDGE_CONFIG_FILE", str(tmp_path / "c.json"))
    monkeypatch.setenv("CLI_BRIDGE_OLLAMA_COST", "free")     # env wins over the file
    cli.main(["set-cost", "ollama", "limited"])
    assert "env wins" in capsys.readouterr().out


def test_setup_write_keeps_profile_commented(tmp_path, monkeypatch, capsys):
    # An uncommented CLI_BRIDGE_PROFILE in the template would count as "explicitly chosen"
    # once sourced, silently disabling the first-run setup guidance.
    path = tmp_path / "cli-bridge.env"
    cli.main(["setup", "--write", str(path)])
    line = next(ln for ln in path.read_text().splitlines() if "CLI_BRIDGE_PROFILE" in ln)
    assert line.lstrip().startswith("#")
