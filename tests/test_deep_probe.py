"""doctor --deep remembers each probe and reports what drifted since the previous one."""
import asyncio

from cli_bridge import lanes, reports, runner, server, telemetry


def _run_lane(ok: bool):
    async def run_lane(lane, args, **kw):
        return runner.RunResult(ok, "OK" if ok else "boom", "ok" if ok else "failed")
    return run_lane


def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "t.sqlite"))
    telemetry._reset_for_tests()
    lane = next(ln for ln in lanes.all_lanes() if ln.key == "ollama")   # free lane that lists models
    out = {"version": "ollama version is 0.20.0", "models": "NAME  ID  SIZE\ngemma4:e4b  ab12  9 GB\n"}

    async def fake_arun(argv, timeout_s, *a, **k):
        which = "version" if list(argv[1:]) == list(lane.version_args) else "models"
        return runner.RunResult(True, out[which], "ok")
    monkeypatch.setattr(reports.runner, "arun", fake_arun)
    return lane, out


def test_first_probe_then_drift(monkeypatch, tmp_path):
    lane, out = _setup(monkeypatch, tmp_path)
    first = asyncio.run(reports.doctor_deep("", [lane], is_host=lambda ln, h: False,
                                            run_lane=_run_lane(True)))
    assert "✅ responds" in first and "0.20.0" in first and "Changed since" not in first
    assert telemetry.probes_get()["ollama"]["models"] == ["gemma4:e4b"]
    out["version"] = "ollama version is 0.21.0"
    out["models"] = "NAME  ID  SIZE\nqwen4:8b  cd34  5 GB\n"
    second = asyncio.run(reports.doctor_deep("", [lane], is_host=lambda ln, h: False,
                                             run_lane=_run_lane(False)))
    assert "## Changed since last deep probe" in second
    assert "✅ → ❌ failed" in second and "0.20.0 → ollama version is 0.21.0" in second
    assert "+qwen4:8b" in second and "-gemma4:e4b" in second


def test_no_change_says_so(monkeypatch, tmp_path):
    lane, _ = _setup(monkeypatch, tmp_path)
    for _ in range(2):
        text = asyncio.run(reports.doctor_deep("", [lane], is_host=lambda ln, h: False,
                                               run_lane=_run_lane(True)))
    assert "_nothing changed_" in text


def test_doctor_nudges_until_probed(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert "No deep probe yet" in server._doctor("")
    telemetry.probes_put({"ollama": {"ok": True, "kind": "ok", "version": "", "models": []}})
    assert "No deep probe yet" not in server._doctor("")
