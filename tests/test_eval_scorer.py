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
