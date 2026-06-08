"""Offline, deterministic tests for the quality eval — no network, no real CLI.

Two jobs:
  1. CALIBRATION GATE — for every fixture, the scorer must give ~100% recall on the canned
     "ideal" reviewer findings (and zero false alarms on clean fixtures). If this fails, the
     SCORER is broken, not the models — so a live result would be meaningless. CI guards it.
  2. Scorer unit behaviour — location tolerance, keyword AND-of-OR, greedy 1:1, precheck
     exclusion, decoy classification — plus a wiring test that runs both arms through the real
     review_diff engine with replayed replies.
"""
import asyncio
import json

import pytest

from cli_bridge import eval as ev
from cli_bridge import findings, lanes, runner


def _fixtures():
    fx = ev.load_evalset(ev.evalset_dir())
    assert fx, "eval corpus is empty — tests/fixtures/evalset is missing"
    return fx


# ── calibration gate: prove the SCORER, not the models ──────────────────────────────────────

def test_corpus_loads_and_has_expected_shape():
    fx = _fixtures()
    summ = ev.corpus_summary(fx)
    assert summ["fixtures"] >= 12
    assert summ["bugs"] >= 10
    assert summ["clean_fixtures"] >= 2          # decoy fixtures that punish over-detection
    assert len(summ["by_category"]) >= 6        # diverse reasoning-bug categories
    # v3 corpus: at least one MULTI-bug fixture (>1 bug) and decoys living INSIDE buggy fixtures
    assert any(len(f.bugs) > 1 for f in fx), "no multi-bug fixture — scorer's 1:1 matching untested"
    assert any(f.bugs and f.decoys for f in fx), "no decoy inside a buggy fixture"


def test_permutation_test_is_deterministic_and_separates_signal():
    # No difference -> high p (identical samples can never beat their own |Δ|=0).
    a = [0.4, 0.5, 0.6, 0.5, 0.45, 0.55]
    assert ev._permutation_test(a, list(a), n=2000, seed=0) == 1.0
    # Clear separation -> low p, and DETERMINISTIC (same seed -> same value).
    lo = [0.0, 0.1, 0.05, 0.15, 0.1, 0.0]
    hi = [0.9, 1.0, 0.95, 0.85, 1.0, 0.9]
    p1 = ev._permutation_test(lo, hi, n=2000, seed=0)
    p2 = ev._permutation_test(lo, hi, n=2000, seed=0)
    assert p1 == p2 and p1 < 0.05
    # Empty input is a non-result, not a crash.
    assert ev._permutation_test([], [1.0], n=100, seed=0) == 1.0


@pytest.mark.parametrize("fx", _fixtures(), ids=lambda f: f.id)
def test_calibration_ideal_findings_score_full_recall(fx):
    """The ideal reviewer (canned) must be scored as catching every bug at full recall, with no
    false positives. This is what guarantees we're measuring the models, not the matcher."""
    sc = ev.score_fixture(fx.ideal, fx)
    if fx.bugs:
        assert sc.tp == sc.n_bugs, f"{fx.id}: scorer missed an ideal finding ({sc.caught_ids})"
        assert sc.fn == 0
    assert sc.fp_decoy == 0, f"{fx.id}: ideal flagged a decoy"
    assert sc.fp_other == 0, f"{fx.id}: ideal produced an off-target finding"


# ── scorer unit behaviour ───────────────────────────────────────────────────────────────────

def _bug(**kw):
    base = dict(id="b", category="c", file="x.py", line=10, line_tolerance=3,
                severity="high", keyword_groups=[["leak"]])
    base.update(kw)
    return ev.ExpectedBug(**base)


def _fx(bugs=None, decoys=None):
    return ev.Fixture(id="t", diff="", bugs=bugs or [], decoys=decoys or [], ideal=[], path=None)


def _f(**kw):
    base = dict(severity="high", title="t", file="x.py", line=10, evidence="", recommendation="")
    base.update(kw)
    return base


def test_match_needs_location_and_keyword():
    bug = _bug(keyword_groups=[["leak"]])
    assert ev.score_fixture([_f(evidence="resource leak here")], _fx([bug])).tp == 1
    # right place, wrong topic -> not a match
    assert ev.score_fixture([_f(evidence="totally unrelated")], _fx([bug])).tp == 0
    # right topic, wrong file -> not a match
    assert ev.score_fixture([_f(file="other.py", evidence="leak")], _fx([bug])).tp == 0


def test_line_tolerance_boundary():
    bug = _bug(line=10, line_tolerance=3, keyword_groups=[["leak"]])
    assert ev.score_fixture([_f(line=13, evidence="leak")], _fx([bug])).tp == 1   # within
    assert ev.score_fixture([_f(line=14, evidence="leak")], _fx([bug])).tp == 0   # just outside


def test_keyword_groups_are_and_of_or():
    bug = _bug(keyword_groups=[["none", "null"], ["attribute", "deref"]])
    assert ev.score_fixture([_f(evidence="None attribute error")], _fx([bug])).tp == 1
    # only one group satisfied -> not a match (groups are AND)
    assert ev.score_fixture([_f(evidence="None value")], _fx([bug])).tp == 0


def test_greedy_one_to_one():
    bug = _bug(keyword_groups=[["leak"]])
    sc = ev.score_fixture([_f(evidence="leak"), _f(evidence="leak again")], _fx([bug]))
    assert sc.tp == 1            # one bug can absorb only one finding
    assert sc.fp_other == 1      # the second is an unmatched false positive


def test_precheck_findings_excluded_by_default():
    bug = _bug(keyword_groups=[["leak"]])
    pf = _f(evidence="leak", models=[findings.STATIC_SOURCE])
    assert ev.score_fixture([pf], _fx([bug])).tp == 0                       # excluded
    assert ev.score_fixture([pf], _fx([bug]), include_prechecks=True).tp == 1
    # a finding the static net AND a model raised (merged models) is NOT excluded
    merged = _f(evidence="leak", models=[findings.STATIC_SOURCE, "gpt"])
    assert ev.score_fixture([merged], _fx([bug])).tp == 1


def test_decoy_classified_as_fp_decoy():
    decoy = ev.Decoy(file="x.py", line=10, line_tolerance=3, reason="rename")
    sc = ev.score_fixture([_f(line=11, evidence="renamed thing may break callers")], _fx([], [decoy]))
    assert sc.fp_decoy == 1 and sc.fp_other == 0


# ── confidence calibration (ECE + Brier + signed gap over planted-bug ground truth) ──────────

def test_score_fixture_emits_calib_pairs_anchored_to_the_matcher():
    bug = _bug(line=10, keyword_groups=[["leak"]])
    tp = _f(line=10, evidence="leak", models=["gpt", "gemini", "mistral"])    # consensus, correct
    fp = _f(line=50, evidence="totally unrelated", models=["gpt"])            # single, wrong
    sc = ev.score_fixture([tp, fp], _fx([bug]), total_reviewers=3)
    assert (1.0, True) in sc.calib                       # 3/3 agreement, matched a bug
    assert (round(1 / 3, 6), False) in [(round(p, 6), c) for p, c in sc.calib]   # 1/3, an FP
    assert len(sc.calib) == 2


def test_score_fixture_no_calib_without_reviewer_count():
    bug = _bug(keyword_groups=[["leak"]])
    sc = ev.score_fixture([_f(evidence="leak")], _fx([bug]))   # total_reviewers defaults to 0
    assert sc.calib == []                                # confidence is meaningless for 1 reviewer


def test_calibration_values_and_discrete_bins():
    # Hand-built: 3 discrete agreement levels (consensus/majority/single), N=60 ≥ 50.
    pairs = ([(1.0, True)] * 27 + [(1.0, False)] * 3          # pred 1.0, acc 0.90, n=30
             + [(0.5, True)] * 10 + [(0.5, False)] * 10       # pred 0.5, acc 0.50, n=20
             + [(1 / 3, True)] * 2 + [(1 / 3, False)] * 8)    # pred .333, acc 0.20, n=10
    out = ev.calibration(pairs)
    assert out["n"] == 60 and out["ece_reliable"] is True
    assert out["ece"] == pytest.approx(0.072222, abs=1e-4)
    assert out["brier"] == pytest.approx(0.162963, abs=1e-4)
    assert out["signed_gap"] == pytest.approx(0.072222, abs=1e-4)   # +ve → overconfident
    # one bin per DISTINCT pred value, sorted, never empty
    assert [b["n"] for b in out["bins"]] == [10, 20, 30]
    assert out["bins"][-1]["acc"] == pytest.approx(0.9)


def test_calibration_suppresses_ece_below_n50():
    pairs = [(1.0, True), (0.5, False), (1 / 3, True)]    # N=3 < 50
    out = ev.calibration(pairs)
    assert out["ece"] is None and out["ece_reliable"] is False
    assert out["brier"] is not None and out["signed_gap"] is not None   # always defined
    assert out["n"] == 3


def test_calibration_empty_is_a_non_result():
    out = ev.calibration([])
    assert out == {"n": 0, "ece": None, "brier": None, "signed_gap": None,
                   "bins": [], "ece_reliable": False}


def test_render_markdown_includes_calibration_table():
    arm = ev.ArmRun(tp=2, n_bugs=2, calib=[(1.0, True), (0.5, False), (1 / 3, True)])
    res = ev.EvalResult(council=[arm], single=[arm], fixtures=_fx([_bug()]) and [_fx([_bug()])],
                        council_lanes=["gpt", "gemini"], single_lane="gpt", k=2)
    md = ev.render_markdown(res)
    assert "Confidence calibration" in md
    assert "Brier" in md and "signed gap" in md
    assert "n/a (N=" in md                               # 3 pairs < 50 → ECE suppressed, not faked


def test_severity_exact_counted():
    bug = _bug(line=10, severity="blocker", keyword_groups=[["leak"]])
    sc = ev.score_fixture([_f(line=10, severity="blocker", evidence="leak")], _fx([bug]))
    assert sc.tp == 1 and sc.sev_exact == 1
    sc2 = ev.score_fixture([_f(line=10, severity="low", evidence="leak")], _fx([bug]))
    assert sc2.tp == 1 and sc2.sev_exact == 0


# ── self-consistency arm: K copies share a spawn, differ only by display ──────────────────────

def test_selfconsistency_lanes_distinct_display_same_key():
    base = lanes.LaneSpec("gpt", "GPT", "echo", lambda *a: [])
    copies = ev.selfconsistency_lanes(base, 4)
    assert len(copies) == 4
    assert all(c.key == "gpt" for c in copies)                 # identical spawn
    assert [c.display for c in copies] == ["GPT#1", "GPT#2", "GPT#3", "GPT#4"]


# ── end-to-end wiring: both arms run through the REAL review_diff engine ───────────────────────

def _replay_run_lane(fixtures):
    """A fake lane that returns each fixture's ideal findings, keyed by the file path embedded in
    the review prompt. Proves council and single arms both drive review_diff correctly."""
    table = {}
    for fx in fixtures:
        for line in fx.diff.splitlines():
            if line.startswith("+++ b/"):
                table[line[6:].strip()] = json.dumps(fx.ideal)

    async def run_lane(lane, args, *, tool="ask", terse=True):
        task = args["task"]
        for path, reply in table.items():
            if path in task:
                return runner.RunResult(True, reply, "ok", latency_ms=1)
        return runner.RunResult(True, "[]", "ok", latency_ms=1)
    return run_lane


def _lane(key):
    return lanes.LaneSpec(key, key.upper(), "echo", lambda *a: [])


def test_evaluate_end_to_end_both_arms_full_recall_on_ideal():
    fx = _fixtures()
    run_lane = _replay_run_lane(fx)
    council = [_lane(k) for k in ("a", "b", "c", "d")]
    res = asyncio.run(ev.evaluate(
        fx, council, _lane("solo"), k=4, run_lane=run_lane, repeats=1))
    # ideal replies -> both arms catch every bug; the eval is wired right
    assert res.council[0].recall == 1.0
    assert res.single[0].recall == 1.0
    assert res.council[0].fp_other == 0 and res.single[0].fp_other == 0
    md = ev.render_markdown(res)
    assert "Quality eval" in md and "No measurable difference" in md
    assert "Where each arm won" in md
    data = ev.result_dict(res)
    assert data["k"] == 4 and data["single_lane"] == "solo"
    assert data["corpus"]["bugs"] >= 10
    # per-bug win/loss is in the JSON too (same source as the md table); ideal -> all caught
    assert data["bugs"] and all(v["council"] and v["single"] for v in data["bugs"].values())


def test_evaluate_council_beats_a_silent_single():
    """If the single lane stays silent (returns no findings) and the council answers, the council
    must score strictly higher — sanity that the comparison can detect a difference."""
    fx = _fixtures()
    good = _replay_run_lane(fx)

    async def silent(lane, args, *, tool="ask", terse=True):
        return runner.RunResult(True, "[]", "ok", latency_ms=1)

    async def run_lane(lane, args, *, tool="ask", terse=True):
        # council lanes (a..d) answer; the solo lane is mute
        if lane.key.startswith("solo"):
            return await silent(lane, args)
        return await good(lane, args)

    council = [_lane(k) for k in ("a", "b", "c", "d")]
    res = asyncio.run(ev.evaluate(
        fx, council, _lane("solo"), k=4, run_lane=run_lane, repeats=1))
    assert res.council[0].recall > res.single[0].recall
    assert res.single[0].recall == 0.0
    assert res.single[0].failed_fixtures == 0          # silent (ran, found nothing) is NOT a failure


def test_evaluate_flags_throttled_arm_as_unreliable():
    """A lane that errors/rate-limits (review fails outright) is flagged failed — distinct from a
    clean 0%. Guards against reading a throttled 0% arm as 'single models are useless'."""
    fx = _fixtures()
    good = _replay_run_lane(fx)

    async def run_lane(lane, args, *, tool="ask", terse=True):
        if lane.key.startswith("solo"):
            return runner.RunResult(False, "rate limited", "empty")   # single lane: every call fails
        return await good(lane, args)

    council = [_lane(k) for k in ("a", "b", "c", "d")]
    res = asyncio.run(ev.evaluate(
        fx, council, _lane("solo"), k=4, run_lane=run_lane, repeats=1))
    assert res.single[0].failed_fixtures == len(fx)    # every single-arm review failed
    assert res.council[0].failed_fixtures == 0
    assert "Unreliable" in ev.render_markdown(res)
    assert ev.result_dict(res)["single"]["failed_fixtures"][0] == len(fx)
