"""Debate/consensus hardening from the June 2026 field report: grounding contract,
fact-check pass, summary_only, independent judge, brief linter, provenance tags,
anti-unanimity steelman, rate_lane hook."""
import asyncio

from cli_bridge import workflows
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def _lane(key, display=None, **kw):
    return LaneSpec(key, display or key, "echo", lambda *x: [], **kw)


def _panel(n=3):
    keys = ["gemini", "gpt", "mistral", "opencode", "extra"][:n]
    return [_lane(k, k.capitalize()) for k in keys]


def _recorder(rec, judge_says="UNANIMOUS: no\nVerdict text."):
    async def run_lane(lane, args, *, tool="ask", terse=True):
        rec.append({"lane": lane.key, "task": args["task"], "tool": tool})
        t = args["task"]
        if "UNANIMOUS" in t and "debated the question" in t:
            return RunResult(True, judge_says, "ok")
        if "fact-checker" in t:
            return RunResult(True, "CONFIRMED: x\nUNVERIFIED: `ollama pull bogus:tag`", "ok")
        if "STEELMAN" in t:
            return RunResult(True, "strongest case against...", "ok")
        return RunResult(True, f"pos {lane.display}", "ok")
    return run_lane


# ── FR-1 grounding contract ──────────────────────────────────────────────────────────────

def test_context_pack_read_into_every_debater_prompt(tmp_path):
    f = tmp_path / "facts.md"
    f.write_text("OOM reproduced 3 times on 16GB.")
    rec = []
    asyncio.run(workflows.debate(
        _panel(3), {"task": "q?", "rounds": 0, "context_files": [str(f)]}, _recorder(rec)))
    openers = [c for c in rec if "pos" not in c["task"] and "CONTEXT PACK" in c["task"]]
    assert openers, "context pack missing from debater prompts"
    assert all("OOM reproduced" in c["task"] for c in openers)
    assert all("facts.md" in c["task"] for c in openers)


def test_context_pack_truncates_and_caps(tmp_path, monkeypatch):
    from cli_bridge import config
    monkeypatch.setattr(config, "CONTEXT_FILE_MAX_CHARS", 50)
    big = tmp_path / "big.txt"
    big.write_text("x" * 500)
    files = [str(big)] + [str(tmp_path / f"missing{i}") for i in range(6)]
    pack, notes = workflows.build_context_pack(files)
    assert "truncated at 50 chars" in pack
    body = pack.rsplit("---\n", 1)[1]                      # file body after its header line
    assert body.count("x") == 50
    assert any("dropped" in n for n in notes)              # cap 5 → 2 dropped
    assert any("unreadable" in n for n in notes)           # missing files noted, not fatal


def test_context_pack_unreadable_only_is_not_fatal(tmp_path):
    pack, notes = workflows.build_context_pack([str(tmp_path / "nope.md")])
    assert pack == "" and any("unreadable" in n for n in notes)


def test_context_pack_relative_resolves_against_cwd(tmp_path):
    (tmp_path / "ctx.md").write_text("relative fact")
    pack, _ = workflows.build_context_pack(["ctx.md"], cwd=str(tmp_path))
    assert "relative fact" in pack


# ── M11-2 preflight data manifest (debate) ───────────────────────────────────────────────

def test_debate_dry_run_manifest_spawns_nothing(tmp_path):
    f = tmp_path / "facts.md"
    f.write_text("verified: 3 OOMs on 16GB")
    rec = []
    out = asyncio.run(workflows.debate(
        _panel(3), {"task": "q?", "context_files": [str(f)], "dry_run": True}, _recorder(rec)))
    assert rec == []                                        # no lane spawned
    assert "Preflight data manifest" in out
    assert "facts.md" in out
    # each debater vendor is named as a recipient
    assert "Gemini" in out and "Gpt" in out


# ── FR-2 fact-check pass ─────────────────────────────────────────────────────────────────

def test_fact_check_runs_by_default_and_reports_unverified():
    rec = []
    out = asyncio.run(workflows.debate(_panel(3), {"task": "q?", "rounds": 0}, _recorder(rec)))
    assert "## ⚠️ Fact-check" in out
    assert "ollama pull bogus:tag" in out                  # the hallucinated tag is surfaced
    assert any("fact-checker" in c["task"] for c in rec)


def test_fact_check_off_switch():
    rec = []
    out = asyncio.run(workflows.debate(
        _panel(3), {"task": "q?", "rounds": 0, "fact_check": False}, _recorder(rec)))
    assert "## ⚠️ Fact-check" not in out
    assert not any("fact-checker" in c["task"] for c in rec)
    assert '"fact_check": "off"' in out                    # honest in the trace


# ── FR-3 summary_only ────────────────────────────────────────────────────────────────────

def test_debate_summary_only_drops_full_positions():
    out_full = asyncio.run(workflows.debate(_panel(3), {"task": "q?", "rounds": 0},
                                            _recorder([])))
    out_sum = asyncio.run(workflows.debate(
        _panel(3), {"task": "q?", "rounds": 0, "summary_only": True}, _recorder([])))
    assert "## Full positions" in out_full and "<details>" in out_full
    assert "## Full positions" not in out_sum and "<details>" not in out_sum
    assert "## Final answer" in out_sum                    # the verdict always survives
    assert len(out_sum) < len(out_full)


def test_consensus_summary_only_drops_all_answers():
    async def run_lane(lane, args, *, tool="ask", terse=True):
        t = args["task"]
        if "chairman of a model council" in t:
            return RunResult(True, "final", "ok")
        if "Rank them best to worst" in t:
            return RunResult(True, "RANKING: A, B, C", "ok")
        return RunResult(True, f"ans {lane.display}", "ok")
    out = asyncio.run(workflows.consensus(_panel(3), {"task": "q", "summary_only": True},
                                          run_lane))
    assert "## All answers" not in out and "## Final answer" in out


# ── FR-4 judge ∉ debaters ────────────────────────────────────────────────────────────────

def test_judge_excluded_from_debaters_with_three_lanes():
    rec = []
    out = asyncio.run(workflows.debate(_panel(3), {"task": "q?", "rounds": 0}, _recorder(rec)))
    judge_call = next(c for c in rec if "debated the question" in c["task"])
    openers = {c["lane"] for c in rec if "Answer this question" in c["task"]}
    assert judge_call["lane"] not in openers               # the judge never debated
    assert '"judge_independent": true' in out


def test_sparse_pool_self_judges_with_note():
    rec = []
    out = asyncio.run(workflows.debate(_panel(2), {"task": "q?", "rounds": 0}, _recorder(rec)))
    assert '"judge_independent": false' in out
    assert "also debated — sparse pool" in out


def test_allow_self_judge_keeps_everyone_debating():
    rec = []
    asyncio.run(workflows.debate(
        _panel(3), {"task": "q?", "rounds": 0, "allow_self_judge": True}, _recorder(rec)))
    openers = {c["lane"] for c in rec if "Answer this question" in c["task"]}
    assert len(openers) == 3                               # nobody held out


# ── T2.2 peer anonymization (anti prestige-bias) ─────────────────────────────────────────

def test_debate_anonymizes_peers_to_judge_and_legends_in_report():
    rec = []

    async def run_lane(lane, args, *, tool="ask", terse=True):
        rec.append({"lane": lane.key, "task": args["task"]})
        t = args["task"]
        if "debated the question" in t:
            return RunResult(True, "UNANIMOUS: no\nDebater A made the point.", "ok")
        if "fact-checker" in t:
            return RunResult(True, "CONFIRMED: ok", "ok")
        return RunResult(True, "an opinion with no name in it", "ok")   # body carries no vendor name

    report = asyncio.run(workflows.debate(_panel(3), {"task": "q?", "rounds": 1}, run_lane))
    judge_prompt = next(c["task"] for c in rec if "debated the question" in c["task"])
    assert "Debater A" in judge_prompt and "Debater B" in judge_prompt   # neutral labels reach judge
    for name in ("### Gpt", "### Mistral", "### Gemini"):
        assert name not in judge_prompt                      # no real vendor headers in the transcript
    # peers see labels too, and are told not to self-identify
    revise = next(c["task"] for c in rec if "ALL ANSWERS SO FAR" in c["task"])
    assert "Debater" in revise
    assert any("Do not reveal, claim, or guess any participant" in c["task"] for c in rec)
    # the report ties labels back to real lanes for the human
    assert "Labels (judge saw these" in report and "Debater A = " in report


# ── FR-5 brief linter (pure) ─────────────────────────────────────────────────────────────

def test_brief_lint_flags_thin_brief():
    warns = workflows.brief_lint("MLX or Ollama?")
    assert any("short brief" in w for w in warns)
    assert any("options" in w for w in warns)
    assert any("criteria" in w for w in warns)


def test_brief_lint_passes_a_rich_brief():
    rich = ("Decide the inference backend for a 16GB M1. Verified facts: 3 Metal OOMs "
            "reproduced; bench of 10 labeled cases. Options: A) MLX in-process B) Ollama "
            "server C) llama.cpp direct D) keep current. Weigh by: stability under memory "
            "pressure, maintainability, throughput. Constraints: no cloud, single machine, "
            "production weekly run with client deliverable.")
    assert workflows.brief_lint(rich) == []


def test_thin_brief_warning_lands_in_report():
    out = asyncio.run(workflows.debate(_panel(3), {"task": "MLX or Ollama?", "rounds": 0},
                                       _recorder([])))
    assert "Thin brief → thin consensus" in out


# ── FR-6 provenance tags ─────────────────────────────────────────────────────────────────

def test_debater_prompts_require_provenance_tags():
    rec = []
    asyncio.run(workflows.debate(_panel(3), {"task": "q?", "rounds": 1}, _recorder(rec)))
    debater_calls = [c for c in rec if "Answer this question" in c["task"]
                     or "REVISED answer" in c["task"]]
    assert debater_calls
    for c in debater_calls:
        assert "[own-knowledge]" in c["task"] and "[verified]" in c["task"]


# ── FR-7 anti-unanimity steelman ─────────────────────────────────────────────────────────

def test_unanimous_verdict_triggers_steelman_when_opted_in():
    rec = []
    out = asyncio.run(workflows.debate(
        _panel(3), {"task": "q?", "rounds": 0, "steelman": True}, _recorder(
            rec, judge_says="UNANIMOUS: yes\nAll agree: option B.")))
    assert any("STEELMAN" in c["task"] for c in rec)       # one lane argued against
    judge_calls = [c for c in rec if "debated the question" in c["task"]]
    assert len(judge_calls) == 2                           # judge re-concluded
    assert '"unanimous": true' in out
    assert "steelman_round" in out


def test_no_steelman_without_opt_in_or_unanimity():
    rec = []
    asyncio.run(workflows.debate(_panel(3), {"task": "q?", "rounds": 0}, _recorder(
        rec, judge_says="UNANIMOUS: yes\nAll agree.")))    # unanimous but steelman not set
    assert not any("STEELMAN" in c["task"] for c in rec)
    rec2 = []
    asyncio.run(workflows.debate(_panel(3), {"task": "q?", "rounds": 0, "steelman": True},
                                 _recorder(rec2)))         # steelman set but not unanimous
    assert not any("STEELMAN" in c["task"] for c in rec2)


def test_unanimous_marker_stripped_from_displayed_answer():
    out = asyncio.run(workflows.debate(_panel(3), {"task": "q?", "rounds": 0}, _recorder([])))
    answer = out.split("## Final answer", 1)[1]
    assert "UNANIMOUS:" not in answer.split("## ", 1)[0]   # marker parsed out of the verdict


# ── FR-8 rate_lane hook ──────────────────────────────────────────────────────────────────

def test_debate_and_consensus_end_with_rate_lane_hook():
    out = asyncio.run(workflows.debate(_panel(3), {"task": "q?", "rounds": 0}, _recorder([])))
    assert 'rate_lane(lane="' in out and 'mode="deep"' in out

    async def run_lane(lane, args, *, tool="ask", terse=True):
        t = args["task"]
        if "chairman of a model council" in t:
            return RunResult(True, "final", "ok")
        if "Rank them best to worst" in t:
            return RunResult(True, "RANKING: A, B", "ok")
        return RunResult(True, "ans", "ok")
    out2 = asyncio.run(workflows.consensus(_panel(2), {"task": "q"}, run_lane))
    assert 'rate_lane(lane="' in out2


def test_consensus_context_pack_reaches_panelists(tmp_path):
    f = tmp_path / "ctx.md"
    f.write_text("panel ground truth")
    seen = []

    async def run_lane(lane, args, *, tool="ask", terse=True):
        seen.append(args["task"])
        t = args["task"]
        if "chairman" in t:
            return RunResult(True, "final", "ok")
        if "Rank them" in t:
            return RunResult(True, "RANKING: A, B", "ok")
        return RunResult(True, "ans", "ok")

    asyncio.run(workflows.consensus(
        _panel(2), {"task": "q", "context_files": [str(f)]}, run_lane))
    answers = [t for t in seen if "Answer the question" in t]
    assert answers and all("panel ground truth" in t for t in answers)


# ── M12-2: structured VOTE footer + convergence early-stop ────────────────────────────────

def _vote_recorder(rec, conf="0.9", cont="yes", body=None):
    async def run_lane(lane, args, *, tool="ask", terse=True):
        rec.append({"lane": lane.key, "task": args["task"], "tool": tool})
        t = args["task"]
        if "debated the question" in t:
            return RunResult(True, "UNANIMOUS: no\nVerdict.", "ok")
        if "fact-checker" in t:
            return RunResult(True, "CONFIRMED: ok", "ok")
        txt = body(lane) if body else f"answer from {lane.display}"
        return RunResult(True, f"{txt}\nVOTE: confidence={conf}; continue={cont}", "ok")
    return run_lane


def test_vote_rule_reaches_debater_prompts():
    rec = []
    asyncio.run(workflows.debate(_panel(2), {"task": "q", "rounds": 1}, _recorder(rec)))
    debater_prompts = [c["task"] for c in rec
                       if "debated the question" not in c["task"] and "fact-checker" not in c["task"]]
    assert debater_prompts
    assert all("VOTE:" in p and "continue=" in p for p in debater_prompts)


def test_votes_parsed_into_meta_and_report_and_footer_stripped():
    rec = []
    report = asyncio.run(workflows.debate(_panel(2), {"task": "q", "rounds": 1},
                                          _vote_recorder(rec, conf="0.8", cont="no")))
    assert "vote:" in report and "mean confidence 0.8" in report
    assert "VOTE: confidence" not in report          # footer stripped from displayed positions


def test_all_stop_votes_end_debate_early():
    rec = []
    report = asyncio.run(workflows.debate(_panel(2), {"task": "q", "rounds": 3},
                                          _vote_recorder(rec, cont="no")))
    assert "rounds: 1" in report                      # stopped after the first revision round
    assert "all debaters voted to stop" in report


def test_convergence_ends_debate_early():
    rec = []
    # identical answers each round, everyone votes continue=yes -> only convergence can stop it
    report = asyncio.run(workflows.debate(
        _panel(2), {"task": "q", "rounds": 3},
        _vote_recorder(rec, cont="yes", body=lambda ln: "the answer is 42")))
    assert "rounds: 1" in report
    assert "converged" in report


def test_distinct_answers_run_full_round_budget():
    rec = []
    bodies = ["alpha beta gamma delta", "completely unrelated words now",
              "numbers one two three four", "totally different sentence again",
              "more varied content follows", "final unique phrasing here"]
    state = {"i": 0}

    def body(_lane):
        s = bodies[state["i"] % len(bodies)]
        state["i"] += 1
        return s

    report = asyncio.run(workflows.debate(
        _panel(2), {"task": "q", "rounds": 2}, _vote_recorder(rec, cont="yes", body=body)))
    assert "rounds: 2" in report
    assert "early stop" not in report
