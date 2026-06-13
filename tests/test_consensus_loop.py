"""Governance converge-loop: the PURE state machine — no lanes, no network. Asserts the three
guards (blind-verdict-first, no-silent-dismissal, no-self-approval) raise / fail-closed in code."""
import pytest

from cli_bridge import consensus_loop as cl


def _peer(label, stance, issues=()):
    return cl.PeerOpinion(peer=label, stance=stance, issues=list(issues), responded=True)


def _issue(iid, label="Reviewer A", cat="correctness"):
    return cl.CriticalIssue(id=iid, peer=label, title=f"issue {iid}", category=cat)


# ── happy path ──────────────────────────────────────────────────────────────────────────────

def test_converges_round_one_when_peers_and_arbiter_approve():
    loop = cl.ConvergenceLoop()
    loop.prepare_round("plan v1")
    loop.record_blind_verdict("approve")
    loop.add_opinions([_peer("Reviewer A", "approve")])
    loop.submit_adjudication([])
    assert loop.check_convergence() == "converged"
    rep = loop.finalize()
    assert rep["outcome"] == "converged" and rep["settled_round"] == 1 and rep["confidence"] == "high"


# ── guard 1: blind-verdict-first ──────────────────────────────────────────────────────────────

def test_blind_verdict_first_gate():
    loop = cl.ConvergenceLoop()
    loop.prepare_round("p")
    with pytest.raises(cl.ConvergenceError):
        loop.add_opinions([_peer("Reviewer A", "approve")])      # opinions before any blind verdict


def test_blind_verdict_recorded_only_once():
    loop = cl.ConvergenceLoop()
    loop.prepare_round("p")
    loop.record_blind_verdict("approve")
    with pytest.raises(cl.ConvergenceError):
        loop.record_blind_verdict("reject")


# ── guard 2: no-silent-dismissal ──────────────────────────────────────────────────────────────

def test_no_silent_dismissal_unadjudicated_issue_raises():
    loop = cl.ConvergenceLoop()
    loop.prepare_round("p")
    loop.record_blind_verdict("approve")
    loop.add_opinions([_peer("Reviewer A", "reject", [_issue("A-1")])])
    with pytest.raises(cl.ConvergenceError):
        loop.submit_adjudication([])                              # issue A-1 left unruled


def test_no_silent_dismissal_reasonless_dismiss_raises():
    loop = cl.ConvergenceLoop()
    loop.prepare_round("p")
    loop.record_blind_verdict("approve")
    loop.add_opinions([_peer("Reviewer A", "reject", [_issue("A-1")])])
    with pytest.raises(cl.ConvergenceError):
        loop.submit_adjudication([cl.Adjudication("A-1", cl.DISMISS, "")])
    with pytest.raises(cl.ConvergenceError):
        loop.submit_adjudication([cl.Adjudication("A-1", cl.DEFER, "   ")])


def test_accept_needs_no_reason():
    loop = cl.ConvergenceLoop(max_rounds=1)
    loop.prepare_round("p")
    loop.record_blind_verdict("approve")
    loop.add_opinions([_peer("Reviewer A", "reject", [_issue("A-1")])])
    loop.submit_adjudication([cl.Adjudication("A-1", cl.ACCEPT)])  # no reason required for accept
    assert loop.check_convergence() == "unresolved"               # but an accepted issue blocks


# ── guard 3: no-self-approval (fail-closed) ───────────────────────────────────────────────────

def test_arbiter_cannot_self_approve_without_a_responding_peer():
    loop = cl.ConvergenceLoop(max_rounds=1)
    loop.prepare_round("p")
    loop.record_blind_verdict("approve")
    loop.add_opinions([cl.PeerOpinion("Reviewer A", "approve", responded=False)])  # peer lane died
    loop.submit_adjudication([])
    assert loop.check_convergence() == "unresolved"               # peers must carry it


def test_peer_reject_blocks_convergence():
    loop = cl.ConvergenceLoop(max_rounds=1)
    loop.prepare_round("p")
    loop.record_blind_verdict("approve")
    loop.add_opinions([_peer("Reviewer A", "approve"), _peer("Reviewer B", "reject")])
    loop.submit_adjudication([])
    assert loop.check_convergence() == "unresolved"


def test_arbiter_blind_reject_blocks_even_if_peers_approve():
    loop = cl.ConvergenceLoop(max_rounds=1)
    loop.prepare_round("p")
    loop.record_blind_verdict("reject")
    loop.add_opinions([_peer("Reviewer A", "approve")])
    loop.submit_adjudication([])
    assert loop.check_convergence() == "unresolved"


def test_unknown_stance_fails_closed_to_abstain():
    loop = cl.ConvergenceLoop(max_rounds=1)
    loop.prepare_round("p")
    loop.record_blind_verdict("approve")
    loop.add_opinions([cl.PeerOpinion("Reviewer A", "maybe")])    # unrecognised -> abstain
    loop.submit_adjudication([])
    assert loop.current.opinions[0].stance == "abstain"
    assert loop.check_convergence() == "unresolved"               # abstain != approve


def test_deferred_issue_does_not_block_and_is_residual():
    loop = cl.ConvergenceLoop()
    loop.prepare_round("p")
    loop.record_blind_verdict("approve")
    loop.add_opinions([_peer("Reviewer A", "approve", [_issue("A-1", cat="performance")])])
    loop.submit_adjudication([cl.Adjudication("A-1", cl.DEFER, "non-blocking, fix later")])
    assert loop.check_convergence() == "converged"
    rep = loop.finalize()
    assert rep["residual_issues"] and rep["residual_issues"][0]["category"] == "performance"


# ── multi-round + terminal states ─────────────────────────────────────────────────────────────

def test_revise_then_converge_two_rounds_medium_confidence():
    loop = cl.ConvergenceLoop(max_rounds=5)
    loop.prepare_round("v1")
    loop.record_blind_verdict("approve")
    loop.add_opinions([_peer("Reviewer A", "reject", [_issue("A-1")])])
    loop.submit_adjudication([cl.Adjudication("A-1", cl.ACCEPT)])
    assert loop.check_convergence() == "revise"
    loop.request_revision()
    loop.prepare_round("v2")
    loop.record_blind_verdict("approve")
    loop.add_opinions([_peer("Reviewer A", "approve")])
    loop.submit_adjudication([])
    assert loop.check_convergence() == "converged"
    rep = loop.finalize()
    assert rep["rounds"] == 2 and rep["settled_round"] == 2 and rep["confidence"] == "medium"


def test_exhausting_rounds_yields_unresolved():
    loop = cl.ConvergenceLoop(max_rounds=1)
    loop.prepare_round("v1")
    loop.record_blind_verdict("approve")
    loop.add_opinions([_peer("Reviewer A", "reject", [_issue("A-1")])])
    loop.submit_adjudication([cl.Adjudication("A-1", cl.ACCEPT)])
    assert loop.check_convergence() == "unresolved"
    rep = loop.finalize()
    assert rep["outcome"] == "unresolved" and rep["confidence"] == "none"
    assert rep["unaddressed_issues"] and rep["unaddressed_issues"][0]["title"] == "issue A-1"


def test_mark_unresolved_when_revision_unavailable():
    loop = cl.ConvergenceLoop(max_rounds=5)
    loop.prepare_round("v1")
    loop.record_blind_verdict("approve")
    loop.add_opinions([_peer("Reviewer A", "reject", [_issue("A-1")])])
    loop.submit_adjudication([cl.Adjudication("A-1", cl.ACCEPT)])
    assert loop.check_convergence() == "revise"
    loop.mark_unresolved()                                        # e.g. author lane failed to revise
    assert loop.finalize()["outcome"] == "unresolved"


def test_confidence_labels():
    assert cl.confidence_for(1) == "high"
    assert cl.confidence_for(2) == "medium"
    assert cl.confidence_for(3) == "medium"
    assert cl.confidence_for(4) == "low"


def test_finalize_before_terminal_raises():
    loop = cl.ConvergenceLoop()
    loop.prepare_round("p")
    with pytest.raises(cl.ConvergenceError):
        loop.finalize()
