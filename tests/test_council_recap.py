"""Council recap: one-line-per-delegate digest so no answer is ever a blind spot."""
import asyncio

from cli_bridge import council, server, workflows
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult

# ── M.1 disagreement-as-uncertainty ──────────────────────────────────────────────────────

def test_agreement_score_aligned_vs_divergent():
    assert council.agreement_score(["same answer", "same answer"]) == 1.0
    assert council.agreement_score(["only one"]) == 1.0           # <2 -> nothing to compare
    low = council.agreement_score(["the cat sat on the mat quietly",
                                   "quantum chromodynamics governs quarks"])
    assert low < 0.5                                              # very different -> low agreement


# ── M.2 confidence-escalate cascade ───────────────────────────────────────────────────────

def test_escalate_chain_skips_low_confidence():
    a = LaneSpec("a", "A", "echo", lambda *x: [])
    b = LaneSpec("b", "B", "echo", lambda *x: [])

    async def rl(lane, sub, *, tool="ask"):
        if lane.key == "a":
            return RunResult(True, "meh\n[ESCALATE]", "ok")      # low confidence
        return RunResult(True, "confident answer", "ok")

    chosen, attempts = asyncio.run(council._run_chain_escalate([a, b], {"task": "x"}, run_lane=rl))
    assert chosen.key == "b" and len(attempts) == 2              # escalated past a


def test_escalate_accepts_last_even_if_unsure():
    a = LaneSpec("a", "A", "echo", lambda *x: [])
    b = LaneSpec("b", "B", "echo", lambda *x: [])

    async def rl(lane, sub, *, tool="ask"):
        return RunResult(True, "unsure\n[ESCALATE]", "ok")       # both escalate

    chosen, _ = asyncio.run(council._run_chain_escalate([a, b], {"task": "x"}, run_lane=rl))
    assert chosen.key == "b"                                     # last accepted (nowhere to escalate)

# ── one_phrase ──────────────────────────────────────────────────────────────────────────

def test_one_phrase_takes_first_meaningful_line():
    assert workflows.one_phrase("first line\nsecond line") == "first line"


def test_one_phrase_strips_markdown_and_blank_lead():
    assert workflows.one_phrase("\n\n   ## Heading here") == "Heading here"
    assert workflows.one_phrase("- bullet point") == "bullet point"
    assert workflows.one_phrase("> quoted") == "quoted"


def test_one_phrase_truncates_with_ellipsis():
    out = workflows.one_phrase("x" * 200, limit=50)
    assert len(out) == 50 and out.endswith("…")


def test_one_phrase_empty():
    assert workflows.one_phrase("") == "(empty)"
    assert workflows.one_phrase("   \n  ") == "(empty)"


# ── council_recap ───────────────────────────────────────────────────────────────────────

def test_recap_header_counts_answered():
    rows = [("A", True, 10, "ans a"), ("B", False, 0, "quota"), ("C", True, 20, "ans c")]
    out = workflows.council_recap(rows)
    assert out.splitlines()[0] == "## Council — 2/3 answered"


def test_recap_one_line_per_row_with_marks():
    rows = [("LaneA", True, 12, "the answer"), ("LaneB", False, 0, "timeout")]
    out = workflows.council_recap(rows)
    assert "- ✅ **LaneA** _12ms_ — the answer" in out
    assert "- ❌ **LaneB** — timeout" in out          # ms omitted when 0; failure shows reason


def test_recap_omits_zero_latency():
    out = workflows.council_recap([("X", True, 0, "hi")], title="Reviewers")
    assert "_0ms_" not in out and "**X** — hi" in out
    assert out.startswith("## Reviewers — 1/1 answered")


def test_recap_gist_is_first_line_only():
    out = workflows.council_recap([("X", True, 5, "headline\nbig body\nmore")])
    assert "— headline" in out and "big body" not in out


# ── integration: ask_all prepends the recap ──────────────────────────────────────────────

def test_ask_all_output_starts_with_recap(monkeypatch):
    a = LaneSpec("a", "LaneA", "echo", lambda *x: [])
    b = LaneSpec("b", "LaneB", "echo", lambda *x: [])
    monkeypatch.setattr(server.telemetry, "cooldown_remaining", lambda key: 0)

    async def fake_run_lane(lane, args, *, tool="ask", terse=True):
        if lane.key == "a":
            return RunResult(True, "answer from A\nextra detail", "ok", latency_ms=11)
        return RunResult(False, "rate limited", "quota", latency_ms=22)
    monkeypatch.setattr(server, "_run_lane", fake_run_lane)

    out = asyncio.run(server._ask_all([a, b], {"task": "hi"}))
    text = out[0].text
    assert text.startswith("## Council — 1/2 answered")
    assert "- ✅ **LaneA** _11ms_ — answer from A" in text   # gist = first line
    assert "- ❌ **LaneB** _22ms_ — quota" in text           # failed lane: latency + reason
    # full blocks still follow the recap
    assert "## LaneA - OK" in text and "## LaneB - FAILED (quota)" in text
