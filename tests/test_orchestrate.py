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


def test_render_results_counts_and_tags_cache():
    out = orchestrate._render_results([
        {"i": 0, "task": "a", "lane": "x", "ok": True, "output": "hi", "cached": True},
        {"i": 1, "task": "b", "lane": "y", "ok": False, "output": "[failed] boom", "cached": False}],
        "batch_run", "resume_id `run_x`", head="{i}. ")
    assert "# batch_run — 1/2 ok" in out and "resume_id `run_x`" in out
    assert "## 1. ✅ x (cached)" in out and "## 2. ❌ y" in out


# ── fanout_compare (G.3: same task to N lanes, side by side) ───────────────────────────────────

def test_fanout_compare_lists_each_option():
    tel = FakeTelemetry()
    lanes = {"a": _lane("a"), "b": _lane("b")}
    report = asyncio.run(orchestrate.fanout_compare(
        run_lane=_ok_run_lane(), resolve_lane=lanes.get, default_lanes=[lanes["a"], lanes["b"]],
        telemetry=tel, task="fix the bug"))
    assert "fanout_compare" in report
    assert "Option 1" in report and "Option 2" in report


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


# ── lane:model entries (multi-model same-lane council) ─────────────────────────────────────

def test_fanout_compare_lane_model_entries(tmp_path, monkeypatch):
    # Real user need: a council of several FREE models of one gateway lane (e.g. opencode),
    # without hand-writing one custom lane per model.
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    from cli_bridge import orchestrate, telemetry
    from cli_bridge.lanes import LaneSpec
    oc = LaneSpec("opencode", "OC", "echo", lambda *a: [])
    seen = []

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        seen.append((lane.key, args.get("model")))
        return RunResult(True, f"answer from {args.get('model')}", "ok", latency_ms=1)

    out = asyncio.run(orchestrate.fanout_compare(
        run_lane=fake_run_lane, resolve_lane=lambda k: oc if k == "opencode" else None,
        default_lanes=[oc], telemetry=telemetry, task="compare me",
        lanes=["opencode:model-a", "opencode:model-b"]))
    assert seen == [("opencode", "model-a"), ("opencode", "model-b")]
    assert "opencode (model-a)" in out and "opencode (model-b)" in out   # labeled per model


def test_fanout_compare_plain_lane_entries_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    from cli_bridge import orchestrate, telemetry
    from cli_bridge.lanes import LaneSpec
    oc = LaneSpec("gemini", "G", "echo", lambda *a: [])

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "hi", "ok", latency_ms=1)

    out = asyncio.run(orchestrate.fanout_compare(
        run_lane=fake_run_lane, resolve_lane=lambda k: oc if k == "gemini" else None,
        default_lanes=[oc], telemetry=telemetry, task="t", lanes=["gemini"]))
    assert "gemini" in out and "(model" not in out                        # no spurious model tag


# ── converge (governance loop: blind verdict -> peers -> adjudicate -> revise/converge) ─────────

def _converge_lanes():
    return {k: _lane(k) for k in ("gpt", "gemini", "claude")}             # openai / google / anthropic


def test_converge_happy_path_converges_round_one():
    tel = FakeTelemetry()
    lanes = _converge_lanes()
    order = []

    async def rl(lane, args, *, tool="ask", terse=True):
        t = args["task"]
        if "You are the ARBITER. Judge the PLAN" in t:
            order.append("blind")
            return RunResult(True, "looks solid\nVERDICT: APPROVE", "ok", 1)
        if "You are an independent reviewer" in t:
            order.append("peer")
            return RunResult(True, "[]\nSTANCE: APPROVE", "ok", 1)
        return RunResult(True, "PLAN BODY", "ok", 1)                      # author draft

    report = asyncio.run(orchestrate.converge(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=list(lanes.values()),
        telemetry=tel, task="design X", author_lane="gpt"))
    assert "CONVERGED" in report and "confidence high" in report
    assert order.index("blind") < order.index("peer")                    # blind verdict before peers


def test_converge_unresolved_when_blocker_accepted():
    tel = FakeTelemetry()
    lanes = _converge_lanes()

    async def rl(lane, args, *, tool="ask", terse=True):
        t = args["task"]
        if "You are the ARBITER. Judge the PLAN" in t:
            return RunResult(True, "VERDICT: APPROVE", "ok", 1)
        if "Rule on EACH" in t:                                          # arbiter adjudicates
            return RunResult(True, '[{"id":"ReviewerA-1","decision":"accept","reason":"real"}]', "ok", 1)
        if "You are an independent reviewer" in t:
            return RunResult(True, '[{"category":"security","title":"SQLi","detail":"bad"}]\n'
                                   "STANCE: REJECT", "ok", 1)
        return RunResult(True, "PLAN", "ok", 1)

    report = asyncio.run(orchestrate.converge(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=list(lanes.values()),
        telemetry=tel, task="q", author_lane="gpt", max_rounds=1))
    assert "UNRESOLVED" in report and "SQLi" in report and "security" in report


def test_converge_revise_then_converge_two_rounds():
    tel = FakeTelemetry()
    lanes = _converge_lanes()
    st = {"peer_calls": 0}

    async def rl(lane, args, *, tool="ask", terse=True):
        t = args["task"]
        if "You are the ARBITER. Judge the PLAN" in t:
            return RunResult(True, "VERDICT: APPROVE", "ok", 1)
        if "Rule on EACH" in t:
            return RunResult(True, '[{"id":"ReviewerA-1","decision":"accept","reason":"x"}]', "ok", 1)
        if "You are an independent reviewer" in t:
            st["peer_calls"] += 1
            if st["peer_calls"] == 1:                                    # round 1: a real blocker
                return RunResult(True, '[{"title":"bug","detail":"d"}]\nSTANCE: REJECT', "ok", 1)
            return RunResult(True, "[]\nSTANCE: APPROVE", "ok", 1)       # round 2: clean
        return RunResult(True, "PLAN", "ok", 1)                          # author draft + revise

    report = asyncio.run(orchestrate.converge(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=list(lanes.values()),
        telemetry=tel, task="q", author_lane="gpt", max_rounds=3))
    assert "CONVERGED" in report and "Round 2" in report


def _converge_with(arbiter_ruling, peer_reply):
    tel = FakeTelemetry()
    lanes = _converge_lanes()

    async def rl(lane, args, *, tool="ask", terse=True):
        t = args["task"]
        if "You are the ARBITER. Judge the PLAN" in t:
            return RunResult(True, "VERDICT: APPROVE", "ok", 1)
        if "Rule on EACH" in t:
            return RunResult(True, arbiter_ruling, "ok", 1)
        if "You are an independent reviewer" in t:
            return peer_reply
        return RunResult(True, "PLAN", "ok", 1)

    return asyncio.run(orchestrate.converge(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=list(lanes.values()),
        telemetry=tel, task="q", author_lane="gpt", max_rounds=1))


def test_converge_arbiter_cannot_self_approve_when_no_peer_responded():
    report = _converge_with("[]", RunResult(False, "", "timeout", 1))      # the peer lane died
    assert "UNRESOLVED" in report and "(no-run)" in report                # peers must carry it


def test_converge_reasonless_dismiss_counts_as_accepted_blocker():
    report = _converge_with('[{"id":"ReviewerA-1","decision":"dismiss","reason":""}]',
                            RunResult(True, '[{"title":"bug","detail":"d"}]\nSTANCE: APPROVE', "ok", 1))
    assert "UNRESOLVED" in report and "Unresolved blocking issues" in report and "bug" in report


def test_converge_deferred_issue_is_residual_not_blocking():
    report = _converge_with('[{"id":"ReviewerA-1","decision":"defer","reason":"later"}]',
                            RunResult(True, '[{"category":"performance","title":"slow path"}]\n'
                                            "STANCE: APPROVE", "ok", 1))
    assert "CONVERGED" in report and "Deferred (non-blocking)" in report and "slow path" in report


def test_converge_needs_a_distinct_peer():
    tel = FakeTelemetry()
    lanes = {k: _lane(k) for k in ("gpt", "codex")}                      # both openai: no peer left

    async def rl(lane, args, *, tool="ask", terse=True):
        return RunResult(True, "x", "ok", 1)

    report = asyncio.run(orchestrate.converge(
        run_lane=rl, resolve_lane=lanes.get, default_lanes=list(lanes.values()),
        telemetry=tel, task="q", author_lane="gpt"))
    assert report.startswith("[error]") and "peer" in report
