"""Steerable multi-turn builds. Real temp git repo + fake run_lane (no AI CLI, no network).
The fake writes files into the build cwd to drive files-changed / zone / plan-leak logic; the
DoD is a real argv (`true`/`false`). Async control paths (interrupt, cancel) drive run_build as
a task and poke it via build_steer / task.cancel()."""
import asyncio
import os
import subprocess

import pytest

from cli_bridge import buildloop
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def _clean_registry():
    buildloop._reset_for_tests()
    yield
    buildloop._reset_for_tests()


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    _git(["init", "-q"], d)
    _git(["config", "user.email", "t@t.t"], d)
    _git(["config", "user.name", "t"], d)
    (d / "README.md").write_text("base\n")
    _git(["add", "-A"], d)
    _git(["commit", "-qm", "init"], d)
    return d


def _lane():
    return LaneSpec("opencode", "Opencode", "echo", lambda *a: [], caps=("model", "effort", "agent"))


def _writer_fake(prompts, *, write_each_turn=True, on_turn=None):
    """Fake build agent: records each prompt, optionally writes a file into the zone every turn,
    and optionally calls on_turn(n) for side effects (e.g. queue a steer)."""
    async def run_lane(lane, args, *, tool="ask", terse=True):
        prompts.append(args["task"])
        n = len(prompts)
        if write_each_turn:
            p = os.path.join(args["cwd"], "frontend", f"f{n}.txt")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write(f"turn {n}\n")
        if on_turn:
            on_turn(n)
        return RunResult(True, f"did turn {n}", "ok", latency_ms=10)
    return run_lane


def _state(tmp_path):
    return buildloop.BuildState(log_path=str(tmp_path / "build.log"))


# ── steering ──────────────────────────────────────────────────────────────────────────────────

def test_steer_block_appears_in_next_turn(repo, tmp_path):
    prompts = []
    state = _state(tmp_path)
    fake = _writer_fake(prompts, on_turn=lambda n: state.steer_q.append("USE TAILWIND") if n == 1
                        else None)
    report = asyncio.run(buildloop.run_build(
        state, run_lane=fake, lane=_lane(),
        args={"task": "build a page", "target_dir": str(repo), "zone": "frontend"},
        steer_grace_s=0))
    assert len(prompts) == 2                                  # steer queued after turn 1 → turn 2
    assert "USE TAILWIND" in prompts[1] and "<<<HOST_STEERING>>>" in prompts[1]
    assert "built" in report


# ── DoD gate ────────────────────────────────────────────────────────────────────────────────

def test_dod_pass_marks_done_first_turn(repo, tmp_path):
    prompts = []
    report = asyncio.run(buildloop.run_build(
        _state(tmp_path), run_lane=_writer_fake(prompts), lane=_lane(),
        args={"task": "t", "target_dir": str(repo), "zone": "frontend", "dod_cmd": ["true"]},
        steer_grace_s=0))
    assert "done (Definition of Done passed)" in report and len(prompts) == 1


def test_dod_fail_feeds_back_then_stops_at_retry_cap(repo, tmp_path):
    prompts = []
    report = asyncio.run(buildloop.run_build(
        _state(tmp_path), run_lane=_writer_fake(prompts), lane=_lane(),
        args={"task": "t", "target_dir": str(repo), "zone": "frontend",
              "dod_cmd": ["false"], "max_fail_retries": 2},
        steer_grace_s=0))
    assert "kept failing" in report and len(prompts) == 2
    assert "Definition-of-Done check failed" in prompts[1]    # failure fed back as steering


def test_max_turns_bounds_total(repo, tmp_path):
    prompts = []
    report = asyncio.run(buildloop.run_build(
        _state(tmp_path), run_lane=_writer_fake(prompts), lane=_lane(),
        args={"task": "t", "target_dir": str(repo), "zone": "frontend",
              "dod_cmd": ["false"], "max_fail_retries": 99, "max_turns": 3},
        steer_grace_s=0))
    assert "hit the turn cap" in report and len(prompts) == 3


def test_dod_cmd_must_be_list(repo, tmp_path):
    report = asyncio.run(buildloop.run_build(
        _state(tmp_path), run_lane=_writer_fake([]), lane=_lane(),
        args={"task": "t", "target_dir": str(repo), "dod_cmd": "rm -rf /"}, steer_grace_s=0))
    assert "must be a list of strings" in report               # never a shell string


# ── plan-leak signal ──────────────────────────────────────────────────────────────────────────

def test_zero_files_changed_warns_not_kills(repo, tmp_path):
    state = _state(tmp_path)
    report = asyncio.run(buildloop.run_build(
        state, run_lane=_writer_fake([], write_each_turn=False), lane=_lane(),
        args={"task": "t", "target_dir": str(repo), "zone": "frontend"}, steer_grace_s=0))
    assert "built" in report                                   # warned, not killed
    assert "changed 0 files" in open(state.log_path).read()


# ── zone violation (per turn) ─────────────────────────────────────────────────────────────────

def test_turn_zone_violation_aborts(repo, tmp_path):
    async def escaping(lane, args, *, tool="ask", terse=True):
        for rel in ("frontend/ok.txt", "backend/evil.txt"):
            p = os.path.join(args["cwd"], rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write("x")
        return RunResult(True, "wrote", "ok", 10)
    report = asyncio.run(buildloop.run_build(
        _state(tmp_path), run_lane=escaping, lane=_lane(),
        args={"task": "t", "target_dir": str(repo), "zone": "frontend"}, steer_grace_s=0))
    assert "zone violation" in report and "backend/evil.txt" in report
    assert not (repo / "frontend" / "ok.txt").exists()        # in-zone work reverted
    assert (repo / "backend" / "evil.txt").exists()           # escape left for inspection


# ── tail (byte offset, line boundary) ─────────────────────────────────────────────────────────

def test_tail_is_incremental_and_line_bounded(tmp_path):
    state = buildloop.BuildState(log_path=str(tmp_path / "j.log"))
    buildloop.register("jid", state)
    buildloop._append(state.log_path, "line one\nline two\n")
    off, chunk = buildloop.tail("jid", 0)
    assert chunk == "line one\nline two\n" and off == len(chunk.encode())
    buildloop._append(state.log_path, "partial")               # no newline yet
    off2, chunk2 = buildloop.tail("jid", off)
    assert chunk2 == "" and off2 == off                        # incomplete line held back
    buildloop._append(state.log_path, " done\n")
    _off3, chunk3 = buildloop.tail("jid", off)
    assert chunk3 == "partial done\n"


def test_tail_unknown_job_is_none():
    assert buildloop.tail("nope", 0) is None


# ── snapshot (job_status enrichment) ──────────────────────────────────────────────────────────

def test_snapshot_reports_live_progress():
    state = buildloop.BuildState(turn=2, max_turns=12, files_changed=3, zone_label="frontend")
    state.steer_q.append("x")
    buildloop.register("jid", state)
    snap = buildloop.snapshot("jid")
    assert snap["turn"] == 2 and snap["files_changed"] == 3
    assert snap["queued_steers"] == 1 and snap["zone"] == "frontend"
    assert buildloop.snapshot("nope") is None


# ── interrupt vs cancel (async control) ───────────────────────────────────────────────────────

def test_interrupt_cuts_turn_but_keeps_files(repo, tmp_path):
    state = _state(tmp_path)
    buildloop.register("jx", state)
    started = asyncio.Event()

    async def hang(lane, args, *, tool="ask", terse=True):
        p = os.path.join(args["cwd"], "frontend", "partial.txt")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write("partial")
        started.set()
        await asyncio.sleep(30)                                 # cancelled by the interrupt
        return RunResult(True, "never", "ok", 10)

    async def scenario():
        task = asyncio.create_task(buildloop.run_build(
            state, run_lane=hang, lane=_lane(),
            args={"task": "t", "target_dir": str(repo), "zone": "frontend", "max_turns": 1},
            steer_grace_s=0))
        await started.wait()
        msg = buildloop.steer("jx", "", interrupt=True)         # cut the current turn
        return await task, msg

    report, msg = asyncio.run(scenario())
    assert "files written so far are kept" in msg
    assert (repo / "frontend" / "partial.txt").exists()        # files KEPT on interrupt
    assert "interrupted by host" in open(state.log_path).read()


def test_job_cancel_propagates(repo, tmp_path):
    state = _state(tmp_path)
    buildloop.register("jc", state)
    started = asyncio.Event()

    async def hang(lane, args, *, tool="ask", terse=True):
        os.makedirs(os.path.join(args["cwd"], "frontend"), exist_ok=True)
        started.set()
        await asyncio.sleep(30)
        return RunResult(True, "never", "ok", 10)

    async def scenario():
        task = asyncio.create_task(buildloop.run_build(
            state, run_lane=hang, lane=_lane(),
            args={"task": "t", "target_dir": str(repo), "zone": "frontend"}, steer_grace_s=0))
        await started.wait()
        task.cancel()                                          # genuine job cancel (not an interrupt)
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


# ── lock held for the whole build ─────────────────────────────────────────────────────────────

def test_second_build_same_zone_refused_while_first_holds_lock(repo, tmp_path):
    # Acquire the zone lock out-of-band, then a build on that zone must refuse fast.
    zone_rel = "frontend"
    with buildloop.worktrees._zone_lock(str(repo), zone_rel):
        report = asyncio.run(buildloop.run_build(
            _state(tmp_path), run_lane=_writer_fake([]), lane=_lane(),
            args={"task": "t", "target_dir": str(repo), "zone": "frontend"}, steer_grace_s=0))
    assert "already running on zone" in report
