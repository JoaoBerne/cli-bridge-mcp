"""Durable fan-out + presets. run_lane is faked (no AI CLI); the journal is exercised both with
an in-memory FakeTelemetry (deterministic resume logic) and once against real sqlite (WAL)."""
import asyncio

from cli_bridge import orchestrate, telemetry
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def _lane(key):
    return LaneSpec(key, key.title(), "echo", lambda *a: [], caps=("model", "agent"))


class FakeTelemetry:
    """In-memory stand-in for the batch journal so resume logic is deterministic."""
    def __init__(self):
        self.store: dict = {}

    def batch_put(self, run_id, key, status, result=None, error=None):
        self.store.setdefault(run_id, {})[key] = {"status": status, "result": result, "error": error}

    def batch_get(self, run_id):
        return dict(self.store.get(run_id, {}))


def _ok_run_lane(record=None):
    async def run_lane(lane, args, *, tool="ask", terse=True):
        if record is not None:
            record.append((lane.key, args.get("task")))
        return RunResult(True, f"{lane.key}:{(args.get('task') or '')[:20]}", "ok", latency_ms=1)
    return run_lane


# ── batch_run substrate ───────────────────────────────────────────────────────────────────────

def test_batch_respects_concurrency_cap():
    tel = FakeTelemetry()
    lanes = {"a": _lane("a")}
    cur = peak = 0

    async def run_lane(lane, args, *, tool="ask", terse=True):
        nonlocal cur, peak
        cur += 1
        peak = max(peak, cur)
        await asyncio.sleep(0.01)
        cur -= 1
        return RunResult(True, "ok", "ok", 1)

    tasks = [{"lane": "a", "task": f"t{i}"} for i in range(10)]
    _rid, res = asyncio.run(orchestrate.batch_run(
        tasks, run_lane=run_lane, resolve_lane=lanes.get, default_lane=lanes["a"],
        telemetry=tel, max_concurrency=2))
    assert len(res) == 10 and all(r["ok"] for r in res)
    assert peak <= 2                                          # never more than 2 in flight


def test_resume_replays_finished_and_skips_rerun():
    tel = FakeTelemetry()
    lanes = {"a": _lane("a")}
    calls = []
    rl = _ok_run_lane(calls)
    tasks = [{"lane": "a", "task": "one"}, {"lane": "a", "task": "two"}]
    rid, res = asyncio.run(orchestrate.batch_run(
        tasks, run_lane=rl, resolve_lane=lanes.get, default_lane=lanes["a"], telemetry=tel))
    assert len(calls) == 2 and all(r["ok"] for r in res) and not any(r["cached"] for r in res)
    calls.clear()
    rid2, res2 = asyncio.run(orchestrate.batch_run(
        tasks, run_lane=rl, resolve_lane=lanes.get, default_lane=lanes["a"], telemetry=tel,
        run_id=rid))
    assert rid2 == rid and calls == [] and all(r["cached"] for r in res2)  # all replayed


def test_resume_reruns_only_the_failed_task():
    tel = FakeTelemetry()
    lanes = {"a": _lane("a")}
    flip = {"two": False}

    async def rl(lane, args, *, tool="ask", terse=True):
        t = args.get("task")
        if t == "two" and not flip["two"]:
            return RunResult(False, "boom", "failed", 1)     # fails the first run
        return RunResult(True, f"ok:{t}", "ok", 1)

    tasks = [{"lane": "a", "task": "one"}, {"lane": "a", "task": "two"}]
    rid, res = asyncio.run(orchestrate.batch_run(
        tasks, run_lane=rl, resolve_lane=lanes.get, default_lane=lanes["a"], telemetry=tel))
    assert res[0]["ok"] and not res[1]["ok"]
    flip["two"] = True
    _rid2, res2 = asyncio.run(orchestrate.batch_run(
        tasks, run_lane=rl, resolve_lane=lanes.get, default_lane=lanes["a"], telemetry=tel,
        run_id=rid))
    assert res2[0]["cached"]                                  # the finished one was replayed
    assert res2[1]["ok"] and not res2[1]["cached"]           # the failed one re-ran and succeeded


def test_batch_run_threads_per_task_timeout():
    # Regression: batch_run used to DROP task['timeout_s'] (so "raise timeout_s" was a lie).
    tel = FakeTelemetry()
    lanes = {"a": _lane("a")}
    seen = []

    async def rl(lane, args, *, tool="ask", terse=True):
        seen.append(args.get("timeout_s"))
        return RunResult(True, "ok", "ok", 1)

    asyncio.run(orchestrate.batch_run(
        [{"lane": "a", "task": "x", "timeout_s": 300}], run_lane=rl, resolve_lane=lanes.get,
        default_lane=lanes["a"], telemetry=tel))
    assert seen == [300]                                  # the per-task timeout reached run_lane


def test_batch_result_carries_provenance():
    tel = FakeTelemetry()
    lanes = {"a": _lane("a")}

    async def rl(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "hi", "ok", exit_code=0, latency_ms=42, model="m1")

    _rid, res = asyncio.run(orchestrate.batch_run(
        [{"lane": "a", "task": "x"}], run_lane=rl, resolve_lane=lanes.get,
        default_lane=lanes["a"], telemetry=tel))
    r = res[0]
    assert r["model"] == "m1" and r["kind"] == "ok"
    assert r["latency_ms"] == 42 and r["exit_code"] == 0


class _CreditTelemetry(FakeTelemetry):
    """FakeTelemetry that can price tokens, for budget/envelope tests (0.01 credit/token)."""
    def _est_credits(self, lane_key, tokens):
        return tokens * 0.01


def test_estimate_returns_cost_envelope():
    tel = _CreditTelemetry()
    lanes = {"a": _lane("a")}
    env = orchestrate.estimate([{"lane": "a", "task": "x" * 40}], resolve_lane=lanes.get,
                               default_lane=lanes["a"], telemetry=tel)
    assert env["n_calls"] == 1 and env["est_input_tokens_total"] == 10
    assert env["est_credits_min"] == round(10 * 0.01, 4)        # input only
    assert env["est_credits_max"] == round(40 * 0.01, 4)        # input + ~3x output


def test_batch_max_calls_caps_spawns():
    tel = FakeTelemetry()
    lanes = {"a": _lane("a")}
    calls = []
    rl = _ok_run_lane(calls)
    tasks = [{"lane": "a", "task": f"t{i}"} for i in range(5)]
    _rid, res = asyncio.run(orchestrate.batch_run(
        tasks, run_lane=rl, resolve_lane=lanes.get, default_lane=lanes["a"], telemetry=tel,
        max_calls=2))
    assert len(calls) == 2                                       # only 2 spawned
    assert sum(1 for r in res if r["kind"] == "blocked") == 3    # rest skipped, not run


def test_batch_max_credits_skips_over_budget():
    tel = _CreditTelemetry()
    lanes = {"a": _lane("a")}
    calls = []

    async def rl(lane, args, *, tool="ask", terse=True):
        calls.append(1)
        return RunResult(True, "ok", "ok", 1)

    # each task: 10 in-tok -> reserve 40*0.01 = 0.4 credits; budget 1.0 -> 2 fit, 3 skipped.
    tasks = [{"lane": "a", "task": "x" * 40} for _ in range(5)]
    _rid, res = asyncio.run(orchestrate.batch_run(
        tasks, run_lane=rl, resolve_lane=lanes.get, default_lane=lanes["a"], telemetry=tel,
        max_credits=1.0))
    assert len(calls) == 2
    assert sum(1 for r in res if r["kind"] == "blocked") == 3


def test_unknown_lane_is_failed_not_crash():
    tel = FakeTelemetry()
    _rid, res = asyncio.run(orchestrate.batch_run(
        [{"lane": "nope", "task": "x"}], run_lane=_ok_run_lane(), resolve_lane=lambda k: None,
        default_lane=None, telemetry=tel))
    assert not res[0]["ok"] and "no such lane" in res[0]["output"]


def test_batch_journals_to_real_sqlite_wal(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "t.sqlite"))
    telemetry._reset_for_tests()
    lanes = {"a": _lane("a")}
    tasks = [{"lane": "a", "task": f"t{i}"} for i in range(12)]
    rid, res = asyncio.run(orchestrate.batch_run(
        tasks, run_lane=_ok_run_lane(), resolve_lane=lanes.get, default_lane=lanes["a"],
        telemetry=telemetry))                                # the REAL journal (WAL)
    assert all(r["ok"] for r in res)
    journal = telemetry.batch_get(rid)
    assert len(journal) == 12 and all(v["status"] == "done" for v in journal.values())
    telemetry._reset_for_tests()


# ── presets ─────────────────────────────────────────────────────────────────────────────────

def test_refine_plan_distributes_angles_and_is_file_based(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("# my plan\nstep 1 do thing\n")
    tel = FakeTelemetry()
    lanes = {"a": _lane("a"), "b": _lane("b")}
    seen = []

    async def rl(lane, args, *, tool="ask", terse=True):
        seen.append((lane.key, args.get("cwd"), args.get("task")))
        return RunResult(True, f"finding from {lane.key}", "ok", 1)

    report = asyncio.run(orchestrate.refine_plan(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=[lanes["a"], lanes["b"]],
        telemetry=tel, plan_file=str(plan)))
    assert "Plan pressure-test" in report
    assert {s[0] for s in seen} == {"a", "b"}                 # 4 angles round-robined over 2 lanes
    assert all(s[1] == str(tmp_path) for s in seen)          # cwd = the plan's dir
    assert all("plan.md" in s[2] for s in seen)              # prompt points at the file...
    assert all("step 1 do thing" not in s[2] for s in seen)  # ...content NOT recopied inline
    assert "technical flaws" in report                       # angle labels in the grouping


def test_refine_plan_with_judge_synthesises(tmp_path):
    plan = tmp_path / "p.md"
    plan.write_text("plan\n")
    tel = FakeTelemetry()
    lanes = {"a": _lane("a"), "j": _lane("j")}
    report = asyncio.run(orchestrate.refine_plan(
        run_lane=_ok_run_lane(), resolve_lane=lanes.get, default_lanes=[lanes["a"]],
        telemetry=tel, plan_file=str(plan), judge_lane="j"))
    assert "Synthesis (judge:" in report


def test_refine_plan_requires_a_plan():
    tel = FakeTelemetry()
    report = asyncio.run(orchestrate.refine_plan(
        run_lane=_ok_run_lane(), resolve_lane=lambda k: _lane(k), default_lanes=[_lane("a")],
        telemetry=tel))
    assert "pass plan_file" in report


def test_council_review_judge_receives_all_outputs():
    tel = FakeTelemetry()
    lanes = {"a": _lane("a"), "b": _lane("b"), "j": _lane("j")}
    captured = {}

    async def rl(lane, args, *, tool="ask", terse=True):
        if lane.key == "j":
            captured["task"] = args.get("task")
            return RunResult(True, "verdict", "ok", 1)
        return RunResult(True, f"answer-{lane.key}", "ok", 1)

    report = asyncio.run(orchestrate.council_review(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=[lanes["a"], lanes["b"]],
        telemetry=tel, question="Q?", judge_lane="j"))
    assert "answer-a" in captured["task"] and "answer-b" in captured["task"]  # judge sees all N
    assert "Synthesis" in report


def test_map_review_points_at_files_not_inline(tmp_path):
    f1 = tmp_path / "x.py"
    f1.write_text("secret_code_xyz\n")
    tel = FakeTelemetry()
    lanes = {"a": _lane("a")}
    seen = []

    async def rl(lane, args, *, tool="ask", terse=True):
        seen.append((args.get("cwd"), args.get("task")))
        return RunResult(True, "ok", "ok", 1)

    asyncio.run(orchestrate.map_review(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=[lanes["a"]], telemetry=tel,
        files=[str(f1)]))
    assert seen[0][0] == str(tmp_path) and "x.py" in seen[0][1]
    assert "secret_code_xyz" not in seen[0][1]               # file content not recopied


def test_research_verify_two_phase():
    tel = FakeTelemetry()
    lanes = {"a": _lane("a"), "b": _lane("b")}
    report = asyncio.run(orchestrate.research_verify(
        run_lane=_ok_run_lane(), resolve_lane=lanes.get, default_lanes=[lanes["a"], lanes["b"]],
        telemetry=tel, questions=["what is 2+2?"]))
    assert "research_verify" in report and "Verification" in report


def test_render_batch_reports_cache_and_resume():
    out = orchestrate.render_batch("run_x", [
        {"i": 0, "task": "a", "lane": "x", "ok": True, "output": "hi", "cached": True},
        {"i": 1, "task": "b", "lane": "y", "ok": False, "output": "[failed] boom", "cached": False}])
    assert "1/2 ok" in out and "1 replayed" in out and "resume_id `run_x`" in out


# ── verify_repair (G.2: cross-model build -> review -> repair loop) ────────────────────────────

def test_verdict_parse_fail_closed_and_last_wins():
    assert orchestrate._verdict("looks good\nVERDICT: APPROVED") == "APPROVED"
    assert orchestrate._verdict("VERDICT: ISSUES") == "ISSUES"
    assert orchestrate._verdict("no verdict at all") == "ISSUES"           # fail-closed
    assert orchestrate._verdict("VERDICT: ISSUES\nthen\nVERDICT: APPROVED") == "APPROVED"


def _builder_verifier(verdicts):
    """Fake: builder lane returns code; verifier lane returns the next queued verdict."""
    seq = list(verdicts)
    state = {"i": 0}

    async def rl(lane, args, *, tool="ask", terse=True):
        if lane.key == "check":
            v = seq[min(state["i"], len(seq) - 1)]
            state["i"] += 1
            return RunResult(True, f"review notes.\nVERDICT: {v}", "ok", 1)
        return RunResult(True, "an attempt", "ok", 1)
    return rl


def test_verify_repair_approved_first_round():
    lanes = {"build": _lane("build"), "check": _lane("check")}
    report = asyncio.run(orchestrate.verify_repair(
        run_lane=_builder_verifier(["APPROVED"]), resolve_lane=lanes.get,
        default_lanes=[lanes["build"], lanes["check"]], task="write f"))
    assert "APPROVED in 1 round" in report
    assert "Round 1" in report and "Round 2" not in report


def test_verify_repair_loops_then_approves():
    lanes = {"build": _lane("build"), "check": _lane("check")}
    report = asyncio.run(orchestrate.verify_repair(
        run_lane=_builder_verifier(["ISSUES", "APPROVED"]), resolve_lane=lanes.get,
        default_lanes=[lanes["build"], lanes["check"]], task="write f", max_rounds=3))
    assert "APPROVED in 2 round" in report and "Round 2" in report


def test_verify_repair_bounds_at_max_rounds():
    lanes = {"build": _lane("build"), "check": _lane("check")}
    report = asyncio.run(orchestrate.verify_repair(
        run_lane=_builder_verifier(["ISSUES"]), resolve_lane=lanes.get,
        default_lanes=[lanes["build"], lanes["check"]], task="x", max_rounds=2))
    assert "NOT APPROVED after 2 round" in report
    assert "Round 1" in report and "Round 2" in report


def test_verify_repair_needs_a_distinct_verifier():
    lanes = {"only": _lane("only")}
    report = asyncio.run(orchestrate.verify_repair(
        run_lane=_ok_run_lane(), resolve_lane=lanes.get, default_lanes=[lanes["only"]], task="x"))
    assert "needs a SECOND lane" in report


# ── fanout_compare (G.3: same task to N lanes, side by side) ───────────────────────────────────

def test_fanout_compare_lists_each_option():
    tel = FakeTelemetry()
    lanes = {"a": _lane("a"), "b": _lane("b")}
    report = asyncio.run(orchestrate.fanout_compare(
        run_lane=_ok_run_lane(), resolve_lane=lanes.get, default_lanes=[lanes["a"], lanes["b"]],
        telemetry=tel, task="fix the bug"))
    assert "fanout_compare" in report
    assert "Option 1" in report and "Option 2" in report


# ── jury (P3: cross-vendor verification, author≠reviewer family) ──────────────────────────────

def _jury_rl(votes_in_order):
    """Fake: author returns an answer; each verifier (prompt contains 'juror') returns the next vote."""
    seq = list(votes_in_order)
    st = {"i": 0}
    seen = []

    async def rl(lane, args, *, tool="ask", terse=True):
        if "juror" in args["task"]:
            seen.append(lane.key)
            v = seq[min(st["i"], len(seq) - 1)]
            st["i"] += 1
            return RunResult(True, f"review\nVERDICT: {v}", "ok", 1)
        return RunResult(True, "the answer", "ok", 1)
    return rl, seen


def test_jury_approves_on_majority_pass():
    tel = FakeTelemetry()
    lanes = {k: _lane(k) for k in ("gpt", "gemini", "claude")}   # openai / google / anthropic
    rl, _seen = _jury_rl(["PASS", "PASS"])
    report = asyncio.run(orchestrate.jury(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=list(lanes.values()),
        telemetry=tel, task="2+2?", author_lane="gpt"))
    assert "APPROVED" in report and "DEGRADED" not in report


def test_jury_rejects_fail_closed_on_split():
    tel = FakeTelemetry()
    lanes = {k: _lane(k) for k in ("gpt", "gemini", "claude")}
    rl, _seen = _jury_rl(["PASS", "FAIL"])                       # 1/2 pass, threshold 2 -> REJECTED
    report = asyncio.run(orchestrate.jury(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=list(lanes.values()),
        telemetry=tel, task="q", author_lane="gpt"))
    assert "REJECTED" in report


def test_jury_excludes_author_family():
    tel = FakeTelemetry()
    lanes = {k: _lane(k) for k in ("gpt", "codex", "gemini")}    # gpt+codex both openai
    rl, seen = _jury_rl(["PASS", "PASS", "PASS"])
    asyncio.run(orchestrate.jury(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=list(lanes.values()),
        telemetry=tel, task="q", author_lane="gpt"))
    assert "codex" not in seen and "gemini" in seen             # same-family codex excluded


def test_jury_mono_family_degrades():
    tel = FakeTelemetry()
    lanes = {k: _lane(k) for k in ("gpt", "codex")}             # both openai -> no cross-family
    rl, _seen = _jury_rl(["PASS"])
    report = asyncio.run(orchestrate.jury(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=list(lanes.values()),
        telemetry=tel, task="q", author_lane="gpt"))
    assert "DEGRADED" in report                                  # degraded, never an undefined verdict


def test_jury_logs_seat_signal_as_conformity(tmp_path, monkeypatch):
    # Two verifiers split PASS/FAIL → fail-closed REJECTED. The seat signal records each vote's
    # CONFORMITY with the final verdict (live, no ground truth): the FAIL voter agrees with REJECTED,
    # the PASS voter does not. It is conformity, NOT accuracy — that's the whole labelling point.
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "t.sqlite"))
    telemetry._reset_for_tests()
    lanes = {k: _lane(k) for k in ("gpt", "gemini", "claude")}    # openai / google / anthropic
    for _ in range(2):                                            # two runs accumulate votes
        rl, _seen = _jury_rl(["PASS", "FAIL"])
        asyncio.run(orchestrate.jury(
            run_lane=rl, resolve_lane=lanes.get, default_lanes=list(lanes.values()),
            telemetry=telemetry, task="q", author_lane="gpt"))   # the REAL telemetry
    seat = telemetry.seat_report()
    assert seat["gemini"]["n_votes"] == 2 and seat["gemini"]["conformity_rate"] == 0.0  # PASS vs REJECTED
    assert seat["claude"]["n_votes"] == 2 and seat["claude"]["conformity_rate"] == 1.0  # FAIL vs REJECTED
    assert seat["gemini"]["accuracy_rate"] is None               # no eval ground truth in live runs
    telemetry._reset_for_tests()


def test_seat_report_separates_eval_accuracy_from_live_conformity(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "t.sqlite"))
    telemetry._reset_for_tests()
    telemetry.jury_put("r1", [("gpt", "fail", "REJECTED", 1)], source="live")     # conformity
    telemetry.jury_put("r2", [("gpt", "fail", "REJECTED", 1)], source="eval")     # vs ground truth
    telemetry.jury_put("r3", [("gpt", "pass", "REJECTED", None)], source="live")  # abstain-like, undecided
    seat = telemetry.seat_report()
    assert seat["gpt"]["conformity_rate"] == 1.0                 # 1 decided live vote agreed
    assert seat["gpt"]["accuracy_rate"] == 1.0                   # separate eval lens
    assert seat["gpt"]["n_votes"] == 3                           # all rows counted
    telemetry._reset_for_tests()


def test_fanout_compare_judge_recommends_one():
    tel = FakeTelemetry()
    lanes = {"a": _lane("a"), "b": _lane("b"), "j": _lane("j")}
    captured = {}

    async def rl(lane, args, *, tool="ask", terse=True):
        if lane.key == "j":
            captured["task"] = args.get("task")
            return RunResult(True, "adopt option a", "ok", 1)
        return RunResult(True, f"sol-{lane.key}", "ok", 1)

    report = asyncio.run(orchestrate.fanout_compare(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=[lanes["a"], lanes["b"]],
        telemetry=tel, task="fix", judge_lane="j"))
    assert "sol-a" in captured["task"] and "sol-b" in captured["task"]   # judge sees all options
    assert "Synthesis" in report
