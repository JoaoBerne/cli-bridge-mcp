"""Governance converge-loop — a PURE state machine (no I/O, no lanes, no network).

Ports deliberation's consensus loop to cli-bridge's house style (cf. router.py / findings.py):
the LOGIC lives here and is unit-tested without spawning anything; orchestrate.py wraps it with an
injected run_lane to drive real council lanes. The point of the module is that the THREE
governance guarantees are enforced IN CODE, not by trusting a host or model to behave:

  1. blind-verdict-first — the arbiter must commit its OWN independent verdict on a plan BEFORE it
     is shown any peer opinion. Enforced by the state gate (opinions are only accepted after
     `record_blind_verdict`) plus a belt-and-braces check inside `add_opinions`.
  2. no-silent-dismissal — EVERY critical issue a peer raised must be explicitly adjudicated, and a
     dismiss/defer decision must carry a non-empty reason. `submit_adjudication` raises otherwise.
  3. no-self-approval — convergence requires the PEERS to carry it, not the arbiter alone: ≥1 peer
     must have responded, all responding peers must APPROVE, none may REJECT, there must be zero
     accepted (unfixed) critical issues, AND the arbiter's own blind verdict must be APPROVE.
     Fail-closed: any missing / abstaining / malformed signal blocks convergence.

States: await_blind -> await_peers -> await_adjudication -> (converged | await_revision); a
revision opens the next round back at await_blind. The loop is bounded by `max_rounds` (default 5);
exhausting it without convergence yields `unresolved`. Confidence is read off the settling round
(early agreement = high; late = low)."""
from __future__ import annotations

from dataclasses import dataclass, field

# Arbiter / peer stances and arbiter decisions — closed sets, lowercased at the boundary.
APPROVE, REJECT, ABSTAIN = "approve", "reject", "abstain"
_STANCES = {APPROVE, REJECT, ABSTAIN}
ACCEPT, DISMISS, DEFER = "accept", "dismiss", "defer"
_DECISIONS = {ACCEPT, DISMISS, DEFER}
_NEEDS_REASON = {DISMISS, DEFER}

# States.
AWAIT_BLIND = "await_blind"
AWAIT_PEERS = "await_peers"
AWAIT_ADJUDICATION = "await_adjudication"
AWAIT_REVISION = "await_revision"
CONVERGED = "converged"
UNRESOLVED = "unresolved"


class ConvergenceError(RuntimeError):
    """A governance guard was violated — the caller drove the loop out of order or incompletely."""


@dataclass
class CriticalIssue:
    id: str
    peer: str                       # neutral label, e.g. "Reviewer A"
    title: str
    detail: str = ""
    category: str | None = None     # Part-2 taxonomy value (already normalized) or None


@dataclass
class PeerOpinion:
    peer: str                       # neutral label
    stance: str                     # approve | reject | abstain
    issues: list[CriticalIssue] = field(default_factory=list)
    responded: bool = True          # False => the peer lane failed to run (excluded from the vote)


@dataclass
class Adjudication:
    issue_id: str
    decision: str                   # accept | dismiss | defer
    reason: str = ""


@dataclass
class Round:
    index: int
    plan: str
    blind_verdict: str | None = None
    blind_note: str = ""
    opinions: list[PeerOpinion] = field(default_factory=list)
    adjudications: list[Adjudication] = field(default_factory=list)

    def issues(self) -> list[CriticalIssue]:
        return [i for o in self.opinions for i in o.issues]


def _norm_stance(raw) -> str:
    s = str(raw or "").strip().lower()
    return s if s in _STANCES else ABSTAIN          # fail-closed: unknown => abstain, never approve


def confidence_for(round_settled: int) -> str:
    """Earlier agreement is more trustworthy: 1 = high, 2-3 = medium, 4+ = low."""
    if round_settled <= 1:
        return "high"
    if round_settled <= 3:
        return "medium"
    return "low"


class ConvergenceLoop:
    def __init__(self, *, max_rounds: int = 5) -> None:
        self.max_rounds = max(1, int(max_rounds))
        self.state = AWAIT_BLIND
        self.rounds: list[Round] = []
        self.outcome: str | None = None
        self.settled_round: int | None = None

    @property
    def round(self) -> int:
        return len(self.rounds)

    @property
    def current(self) -> Round:
        if not self.rounds:
            raise ConvergenceError("no round started — call prepare_round() first")
        return self.rounds[-1]

    # ── transitions ──────────────────────────────────────────────────────────────────────────

    def prepare_round(self, plan: str) -> Round:
        """Open a round with the author's (possibly revised) plan. Valid at the very start and,
        after `request_revision`, for each subsequent round."""
        if self.state != AWAIT_BLIND:
            raise ConvergenceError(f"cannot start a round from state {self.state!r}")
        r = Round(index=self.round + 1, plan=plan)
        self.rounds.append(r)
        return r

    def record_blind_verdict(self, verdict: str, note: str = "") -> None:
        """The arbiter commits its OWN verdict BEFORE seeing any peer opinion (guard 1)."""
        if self.state != AWAIT_BLIND:
            raise ConvergenceError(f"blind verdict not expected in state {self.state!r}")
        cur = self.current
        if cur.blind_verdict is not None:
            raise ConvergenceError("blind verdict already recorded for this round")
        cur.blind_verdict = _norm_stance(verdict)
        cur.blind_note = str(note or "")
        self.state = AWAIT_PEERS

    def add_opinions(self, opinions: list[PeerOpinion]) -> None:
        """Record peer reviews. The state gate already enforces blind-verdict-first; this re-checks
        it explicitly (guard 1) so the guarantee can't regress if the states are ever refactored."""
        if self.state != AWAIT_PEERS:
            raise ConvergenceError(f"opinions not expected in state {self.state!r}")
        cur = self.current
        if cur.blind_verdict is None:
            raise ConvergenceError("blind-verdict-first violated: no blind verdict on record")
        for o in opinions:
            o.stance = _norm_stance(o.stance)
        cur.opinions = list(opinions)
        self.state = AWAIT_ADJUDICATION

    def submit_adjudication(self, adjudications: list[Adjudication]) -> None:
        """The arbiter rules on EVERY raised issue; dismiss/defer need a reason (guard 2)."""
        if self.state != AWAIT_ADJUDICATION:
            raise ConvergenceError(f"adjudication not expected in state {self.state!r}")
        cur = self.current
        issue_ids = {i.id for i in cur.issues()}
        by_id = {a.issue_id: a for a in adjudications}
        missing = issue_ids - by_id.keys()
        if missing:
            raise ConvergenceError(
                f"no-silent-dismissal violated: issues not adjudicated: {sorted(missing)}")
        for a in adjudications:
            if a.decision not in _DECISIONS:
                raise ConvergenceError(f"unknown adjudication decision {a.decision!r}")
            if a.decision in _NEEDS_REASON and not str(a.reason or "").strip():
                raise ConvergenceError(
                    f"no-silent-dismissal violated: {a.decision} of {a.issue_id!r} needs a reason")
        cur.adjudications = [a for a in adjudications if a.issue_id in issue_ids]

    def check_convergence(self) -> str:
        """Decide the round: 'converged' | 'revise' | 'unresolved'. Advances state."""
        if self.state != AWAIT_ADJUDICATION:
            raise ConvergenceError(f"convergence check not expected in state {self.state!r}")
        cur = self.current
        if self._converged(cur):
            self.state = self.outcome = CONVERGED
            self.settled_round = cur.index
            return "converged"
        if cur.index >= self.max_rounds:
            self.state = self.outcome = UNRESOLVED
            self.settled_round = cur.index
            return "unresolved"
        self.state = AWAIT_REVISION
        return "revise"

    def request_revision(self) -> None:
        """Acknowledge a revise decision and reopen for the next round's blind verdict."""
        if self.state != AWAIT_REVISION:
            raise ConvergenceError(f"revision not expected in state {self.state!r}")
        self.state = AWAIT_BLIND

    def mark_unresolved(self) -> None:
        """Terminal escape when a revision cannot be produced (e.g. the author lane failed)."""
        if self.state != AWAIT_REVISION:
            raise ConvergenceError(f"cannot mark unresolved from state {self.state!r}")
        self.state = self.outcome = UNRESOLVED
        self.settled_round = self.round

    # ── predicates / queries ─────────────────────────────────────────────────────────────────

    def _converged(self, r: Round) -> bool:
        """no-self-approval predicate (guard 3), fail-closed on any weak signal."""
        if r.blind_verdict != APPROVE:                  # the arbiter must independently approve
            return False
        responders = [o for o in r.opinions if o.responded]
        if not responders:                              # peers must carry it — no self-approval
            return False
        if any(o.stance != APPROVE for o in responders):
            return False
        if self.accepted_issues(r):                     # an accepted (unfixed) issue blocks
            return False
        return True

    def accepted_issues(self, r: Round | None = None) -> list[CriticalIssue]:
        r = r or self.current
        accepted = {a.issue_id for a in r.adjudications if a.decision == ACCEPT}
        return [i for i in r.issues() if i.id in accepted]

    def deferred_issues(self, r: Round | None = None) -> list[CriticalIssue]:
        r = r or self.current
        deferred = {a.issue_id for a in r.adjudications if a.decision == DEFER}
        return [i for i in r.issues() if i.id in deferred]

    # ── terminal report ──────────────────────────────────────────────────────────────────────

    def finalize(self) -> dict:
        if self.outcome is None:
            raise ConvergenceError("loop has not reached a terminal state")
        last = self.rounds[-1]
        conf = confidence_for(self.settled_round or self.round) if self.outcome == CONVERGED \
            else "none"
        return {
            "outcome": self.outcome,
            "rounds": self.round,
            "max_rounds": self.max_rounds,
            "settled_round": self.settled_round,
            "confidence": conf,
            "residual_issues": [self._issue_dict(i) for i in self.deferred_issues(last)],
            "unaddressed_issues": [self._issue_dict(i) for i in
                                   (self.accepted_issues(last) if self.outcome == UNRESOLVED else [])],
            "history": [
                {
                    "round": r.index,
                    "blind_verdict": r.blind_verdict,
                    "peers": [{"peer": o.peer, "stance": o.stance, "responded": o.responded,
                               "issues": len(o.issues)} for o in r.opinions],
                    "accepted": len(self.accepted_issues(r)),
                    "deferred": len(self.deferred_issues(r)),
                }
                for r in self.rounds
            ],
        }

    @staticmethod
    def _issue_dict(i: CriticalIssue) -> dict:
        return {"title": i.title, "category": i.category, "peer": i.peer, "detail": i.detail}
