"""Async jobs: start returns fast, result retrievable, failures recorded, cancellation
settles as cancelled, and a restart flips stale 'running' rows to 'interrupted'."""
import asyncio

import pytest

from cli_bridge import jobs, server, telemetry
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("CLI_BRIDGE_TELEMETRY", "on")
    monkeypatch.setenv("CLI_BRIDGE_OVERFLOW_DIR", str(tmp_path / "overflow"))
    telemetry._reset_for_tests()
    jobs._reset_for_tests()
    yield
    telemetry._reset_for_tests()
    jobs._reset_for_tests()


async def _drain():
    """Let scheduled job tasks run to completion."""
    await asyncio.gather(*[j.task for j in jobs._JOBS.values() if j.task is not None],
                         return_exceptions=True)


# ── lifecycle: start → succeed → fetch ────────────────────────────────────────────────────

def test_start_returns_fast_and_succeeds():
    async def scenario():
        async def work():
            return "the council answer"
        job_id = jobs.start_job("ask_all", work, preview="hi")
        assert job_id.startswith("job_")
        assert jobs.status(job_id)["status"] == jobs.RUNNING   # not done yet
        await _drain()
        return job_id
    job_id = asyncio.run(scenario())
    assert jobs.status(job_id)["status"] == jobs.SUCCEEDED
    assert jobs.result(job_id) == (jobs.SUCCEEDED, "the council answer")


def test_result_running_then_done():
    async def scenario():
        gate = asyncio.Event()

        async def work():
            await gate.wait()
            return "done"
        job_id = jobs.start_job("ask_all", work, preview="x")
        assert jobs.result(job_id) == (jobs.RUNNING, "")
        gate.set()
        await _drain()
        return job_id
    job_id = asyncio.run(scenario())
    assert jobs.result(job_id) == (jobs.SUCCEEDED, "done")


def test_failed_job_records_error():
    async def scenario():
        async def boom():
            raise ValueError("kaboom")
        job_id = jobs.start_job("ask_all", boom, preview="x")
        await _drain()
        return job_id
    job_id = asyncio.run(scenario())
    st = jobs.status(job_id)
    assert st["status"] == jobs.FAILED and "kaboom" in st["error"]
    state, body = jobs.result(job_id)
    assert state == jobs.FAILED and "kaboom" in body


# ── cancellation settles as cancelled ──────────────────────────────────────────────────────

def test_cancel_settles_cancelled():
    async def scenario():
        async def forever():
            await asyncio.sleep(60)
            return "never"
        job_id = jobs.start_job("ask_all", forever, preview="x")
        await asyncio.sleep(0)                       # let the task start
        assert jobs.cancel(job_id) == "cancelling"
        await _drain()
        return job_id
    job_id = asyncio.run(scenario())
    assert jobs.status(job_id)["status"] == jobs.CANCELLED


def test_cancel_unknown_and_finished():
    async def scenario():
        async def work():
            return "ok"
        job_id = jobs.start_job("ask_all", work, preview="x")
        await _drain()
        return job_id
    job_id = asyncio.run(scenario())
    assert jobs.cancel("job_nope") == "unknown"
    assert jobs.cancel(job_id) == jobs.SUCCEEDED      # already done


# ── persistence / restart ──────────────────────────────────────────────────────────────────

def test_restart_marks_running_interrupted():
    # simulate a previous process that left a running row, then "restart" (clear memory)
    telemetry.job_put("job_stale", "ask_all", jobs.RUNNING, "old task")
    jobs._reset_for_tests()                           # memory gone, like a fresh process
    n = jobs.mark_interrupted_on_startup()
    assert n == 1
    assert jobs.status("job_stale")["status"] == jobs.INTERRUPTED


def test_unknown_job():
    assert jobs.status("job_missing") is None
    assert jobs.result("job_missing") is None


# ── server dispatch: ask_all_async returns an id, job_result emits the body ─────────────────

def test_ask_all_async_dispatch(monkeypatch):
    a = LaneSpec("a", "LaneA", "echo", lambda *x: [])
    monkeypatch.setattr(server, "installed_lanes", lambda lst: [a])   # deterministic, not PATH
    monkeypatch.setenv("CLI_BRIDGE_HOST", "claude-code")              # 'a' is a delegate
    monkeypatch.setattr(server.telemetry, "cooldown_remaining", lambda key: 0)

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "lane answer", "ok", latency_ms=5)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    async def scenario():
        out = await server.call_tool("ask_all_async", {"task": "hi"})
        text = out[0].text
        assert text.startswith("Started background job `job_")
        job_id = text.split("`")[1]
        await _drain()
        res = await server.call_tool("job_result", {"job_id": job_id})
        return res[0].text
    body = asyncio.run(scenario())
    assert "## Council —" in body and "lane answer" in body
