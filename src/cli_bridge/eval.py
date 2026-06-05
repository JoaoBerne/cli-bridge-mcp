"""Quality eval — does a COUNCIL of distinct models beat one strong model + self-consistency?

The honest question behind the project. The naïve claim "more models = better" is NOT a given
(see SOTA_REVIEW_2026-06.md §A.1: selection > synthesis, and a council can over-detect). So we
measure it, and we publish the result even when the council LOSES.

Design — reuse the review engine UNCHANGED (`workflows.review_diff`), vary ONE thing:

  COUNCIL  = review_diff([N distinct lanes])         — N calls, one role per lane
  SINGLE   = review_diff([single_lane × K copies])   — K calls of the SAME lane (displays #1..#K)

Same call budget (K = N), same roles, same merge/confidence pipeline. The only difference is
"distinct models" vs "repeated samples of one model" — i.e. self-consistency. The copies are made
with dataclasses.replace(spec, display=...): identical spawn, distinct display so the merge counts
them as distinct "reviewers" (findings.confidence keys off `models`, which is the display).

Ground truth: tests/fixtures/evalset/<id>/{case.diff, expected.json, ideal.json}. expected.json
lists REASONING bugs (off-by-one, null deref, races, authz) that the regex prechecks CANNOT catch,
so we measure the MODELS, not the static net. Bugs are locally decidable from the diff alone.

Scorer: deterministic, NO LLM judge. A finding matches a bug iff (a) same file basename and line
within ±tolerance (expected line None → file-level match, tagged weak_loc) AND (b) the keyword
test passes: for EVERY group in `must_match_any`, at least one synonym appears in the normalized
title+evidence+recommendation. Groups are AND, synonyms within a group are OR. Greedy 1:1 matching.
Precheck findings (models == [STATIC_SOURCE]) are excluded by default — they are identical in both
arms, so counting them would only dilute the signal.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import statistics
from dataclasses import dataclass, field

from . import findings as _findings
from . import workflows
from .lanes import LaneSpec

# Repo-local default; not shipped inside the wheel. `cli-bridge eval` outside a checkout must pass
# --fixtures (or set CLI_BRIDGE_EVALSET). src/cli_bridge/eval.py -> repo_root/tests/fixtures/evalset
_DEFAULT_EVALSET = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "evalset"


# ── corpus model ──────────────────────────────────────────────────────────────────────────

@dataclass
class ExpectedBug:
    id: str
    category: str
    file: str | None
    line: int | None
    line_tolerance: int
    severity: str
    keyword_groups: list[list[str]]   # must_match_any: AND of groups, OR of synonyms within


@dataclass
class Decoy:
    file: str | None
    line: int | None
    line_tolerance: int
    reason: str


@dataclass
class Fixture:
    id: str
    diff: str
    bugs: list[ExpectedBug]
    decoys: list[Decoy]
    ideal: list[dict]                 # canned perfect-reviewer findings (calibration + offline)
    path: pathlib.Path


def _bug(d: dict) -> ExpectedBug:
    return ExpectedBug(
        id=str(d.get("id") or d.get("category") or "bug"),
        category=str(d.get("category") or ""),
        file=d.get("file"),
        line=d.get("line"),
        line_tolerance=int(d.get("line_tolerance", 3)),
        severity=str(d.get("severity") or "").strip().lower(),
        keyword_groups=[[str(s) for s in g] for g in (d.get("must_match_any") or [])],
    )


def _decoy(d: dict) -> Decoy:
    return Decoy(file=d.get("file"), line=d.get("line"),
                 line_tolerance=int(d.get("line_tolerance", 3)),
                 reason=str(d.get("reason") or ""))


def load_fixture(d: pathlib.Path) -> Fixture:
    spec = json.loads((d / "expected.json").read_text(encoding="utf-8"))
    ideal_path = d / "ideal.json"
    ideal = json.loads(ideal_path.read_text(encoding="utf-8")) if ideal_path.exists() else []
    return Fixture(
        id=str(spec.get("id") or d.name),
        diff=(d / "case.diff").read_text(encoding="utf-8"),
        bugs=[_bug(b) for b in (spec.get("bugs") or [])],
        decoys=[_decoy(x) for x in (spec.get("decoys") or [])],
        ideal=ideal if isinstance(ideal, list) else [],
        path=d,
    )


def evalset_dir(override: str = "") -> pathlib.Path:
    import os
    cand = (override or os.environ.get("CLI_BRIDGE_EVALSET") or "").strip()
    return pathlib.Path(cand).expanduser() if cand else _DEFAULT_EVALSET


def load_evalset(root: pathlib.Path, only: list[str] | None = None) -> list[Fixture]:
    if not root.exists():
        return []
    dirs = sorted(p for p in root.iterdir() if p.is_dir() and (p / "expected.json").exists())
    if only:
        keep = set(only)
        dirs = [p for p in dirs if p.name in keep]
    return [load_fixture(p) for p in dirs]


# ── deterministic matching ──────────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _basename(p) -> str:
    return (str(p) if p is not None else "").replace("\\", "/").rsplit("/", 1)[-1]


def _kw_match(finding: dict, groups: list[list[str]]) -> bool:
    """Every group must be satisfied (AND); a group is satisfied by any one synonym (OR)."""
    if not groups:
        return True
    blob = _norm(f"{finding.get('title', '')} {finding.get('evidence', '')} "
                 f"{finding.get('recommendation', '')}")
    return all(any(_norm(syn) in blob for syn in group if str(syn).strip()) for group in groups)


def _loc_match(finding: dict, file: str | None, line: int | None, tol: int) -> tuple[bool, bool]:
    """(matched, weak). weak=True means the location was only file-level (expected or actual line
    was None), so the match is real but less precise."""
    weak = False
    if file is not None and _basename(finding.get("file")) != _basename(file):
        return False, False
    if line is None:
        weak = True
    else:
        fl = finding.get("line")
        if fl is None:
            weak = True
        else:
            try:
                if abs(int(fl) - int(line)) > tol:
                    return False, False
            except (TypeError, ValueError):
                weak = True
    return True, weak


def _matches_bug(finding: dict, bug: ExpectedBug) -> tuple[bool, bool]:
    loc_ok, weak = _loc_match(finding, bug.file, bug.line, bug.line_tolerance)
    if not loc_ok:
        return False, False
    return (_kw_match(finding, bug.keyword_groups), weak)


def _is_decoy_hit(finding: dict, decoy: Decoy) -> bool:
    return _loc_match(finding, decoy.file, decoy.line, decoy.line_tolerance)[0]


# ── scoring one arm against one fixture ─────────────────────────────────────────────────────

@dataclass
class FixtureScore:
    fixture_id: str
    n_bugs: int
    caught_ids: list[str] = field(default_factory=list)   # bug ids matched (for win/loss table)
    weak_ids: list[str] = field(default_factory=list)     # matched but only file-level location
    tp: int = 0
    fn: int = 0
    fp_decoy: int = 0                                      # flagged a known-clean decoy line
    fp_other: int = 0                                      # flagged something not in ground truth
    sev_exact: int = 0                                     # of TP, severity matched exactly
    n_findings: int = 0


def score_fixture(findings_list: list[dict], fixture: Fixture, *,
                  include_prechecks: bool = False) -> FixtureScore:
    cands = [f for f in findings_list
             if include_prechecks or f.get("models") != [_findings.STATIC_SOURCE]]
    used = [False] * len(cands)
    sc = FixtureScore(fixture_id=fixture.id, n_bugs=len(fixture.bugs), n_findings=len(cands))
    for bug in fixture.bugs:
        for i, f in enumerate(cands):
            if used[i]:
                continue
            ok, weak = _matches_bug(f, bug)
            if ok:
                used[i] = True
                sc.tp += 1
                sc.caught_ids.append(bug.id)
                if weak:
                    sc.weak_ids.append(bug.id)
                if bug.severity and str(f.get("severity", "")).lower() == bug.severity:
                    sc.sev_exact += 1
                break
    sc.fn = sc.n_bugs - sc.tp
    for i, f in enumerate(cands):
        if used[i]:
            continue
        if any(_is_decoy_hit(f, dc) for dc in fixture.decoys):
            sc.fp_decoy += 1
        else:
            sc.fp_other += 1
    return sc


# ── aggregation across fixtures (one arm, one repeat) ───────────────────────────────────────

@dataclass
class ArmRun:
    tp: int = 0
    fn: int = 0
    n_bugs: int = 0
    fp_decoy: int = 0
    fp_other: int = 0
    sev_exact: int = 0
    n_findings: int = 0
    per_fixture: dict[str, FixtureScore] = field(default_factory=dict)

    @property
    def recall(self) -> float:
        return self.tp / self.n_bugs if self.n_bugs else 0.0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp_decoy + self.fp_other
        return self.tp / denom if denom else 1.0

    @property
    def sev_acc(self) -> float:
        return self.sev_exact / self.tp if self.tp else 0.0


def aggregate(scores: list[FixtureScore]) -> ArmRun:
    a = ArmRun()
    for s in scores:
        a.tp += s.tp
        a.fn += s.fn
        a.n_bugs += s.n_bugs
        a.fp_decoy += s.fp_decoy
        a.fp_other += s.fp_other
        a.sev_exact += s.sev_exact
        a.n_findings += s.n_findings
        a.per_fixture[s.fixture_id] = s
    return a


# ── live runner: each arm reuses review_diff unchanged ──────────────────────────────────────

def selfconsistency_lanes(single: LaneSpec, k: int) -> list[LaneSpec]:
    """K copies of one lane with distinct DISPLAYS (#1..#K) but the same key/argv. The merge
    treats them as K reviewers (confidence keys off display); the spawn is identical each time."""
    return [dataclasses.replace(single, display=f"{single.display}#{i + 1}") for i in range(k)]


async def run_arm(targets: list[LaneSpec], diff: str, run_lane, *,
                  timeout_s: int | None = None) -> list[dict]:
    """One review pass → list of finding dicts. review_diff returns '[error] ...' (not JSON) when
    every reviewer fails; we treat that as zero findings rather than crashing the eval."""
    args = {"diff": diff, "output_format": "json"}
    if timeout_s:
        args["timeout_s"] = timeout_s
    out = await workflows.review_diff(targets, args, run_lane)
    try:
        data = json.loads(out)
    except (ValueError, TypeError):
        return []
    return data.get("findings", []) if isinstance(data, dict) else []


@dataclass
class EvalResult:
    council: list[ArmRun]                 # one ArmRun per repeat
    single: list[ArmRun]
    fixtures: list[Fixture]
    council_lanes: list[str]
    single_lane: str
    k: int


async def evaluate(fixtures: list[Fixture], council: list[LaneSpec], single: LaneSpec, *,
                   k: int, run_lane, repeats: int = 3, include_prechecks: bool = False,
                   timeout_s: int | None = None) -> EvalResult:
    single_arm = selfconsistency_lanes(single, k)
    council_runs: list[ArmRun] = []
    single_runs: list[ArmRun] = []
    for _ in range(max(1, repeats)):
        c_scores, s_scores = [], []
        for fx in fixtures:
            c = await run_arm(council, fx.diff, run_lane, timeout_s=timeout_s)
            s = await run_arm(single_arm, fx.diff, run_lane, timeout_s=timeout_s)
            c_scores.append(score_fixture(c, fx, include_prechecks=include_prechecks))
            s_scores.append(score_fixture(s, fx, include_prechecks=include_prechecks))
        council_runs.append(aggregate(c_scores))
        single_runs.append(aggregate(s_scores))
    return EvalResult(council=council_runs, single=single_runs, fixtures=fixtures,
                      council_lanes=[ln.key for ln in council], single_lane=single.key, k=k)


# ── reporting ───────────────────────────────────────────────────────────────────────────────

def _mean_sd(vals: list[float]) -> tuple[float, float]:
    if not vals:
        return 0.0, 0.0
    return statistics.fmean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0)


def _ci_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Crude 1-sigma overlap test: if the mean±sd bands touch, call it 'no measurable difference'
    rather than declaring a winner from noise."""
    (ma, sa), (mb, sb) = a, b
    lo_a, hi_a = ma - sa, ma + sa
    lo_b, hi_b = mb - sb, mb + sb
    return not (hi_a < lo_b or hi_b < lo_a)


def corpus_summary(fixtures: list[Fixture]) -> dict:
    by_cat: dict[str, int] = {}
    n_bugs = n_decoys = n_clean = 0
    for fx in fixtures:
        n_bugs += len(fx.bugs)
        n_decoys += len(fx.decoys)
        if not fx.bugs:
            n_clean += 1
        for b in fx.bugs:
            by_cat[b.category] = by_cat.get(b.category, 0) + 1
    return {"fixtures": len(fixtures), "bugs": n_bugs, "decoys": n_decoys,
            "clean_fixtures": n_clean, "by_category": dict(sorted(by_cat.items()))}


def render_markdown(res: EvalResult) -> str:
    c_rec = _mean_sd([r.recall for r in res.council])
    s_rec = _mean_sd([r.recall for r in res.single])
    c_prec = _mean_sd([r.precision for r in res.council])
    s_prec = _mean_sd([r.precision for r in res.single])
    c_fpd = _mean_sd([float(r.fp_decoy) for r in res.council])
    s_fpd = _mean_sd([float(r.fp_decoy) for r in res.single])
    c_sev = _mean_sd([r.sev_acc for r in res.council])
    s_sev = _mean_sd([r.sev_acc for r in res.single])
    n_bugs = res.council[0].n_bugs if res.council else 0
    overlap = _ci_overlap(c_rec, s_rec)
    delta = c_rec[0] - s_rec[0]
    if overlap:
        verdict = ("**No measurable difference** in recall (mean±sd bands overlap) — at this corpus "
                   "size the council neither beats nor loses to single-model self-consistency.")
    elif delta > 0:
        verdict = (f"Council recall is higher by {delta:+.0%} (bands disjoint at 1σ). Directional, "
                   "not a leaderboard.")
    else:
        verdict = (f"Single+self-consistency recall is higher by {-delta:+.0%}. Consistent with "
                   "§A.1 (selection > naïve synthesis) — a council is not automatically better.")

    def cell(ms): return f"{ms[0]:.0%} ± {ms[1]:.0%}"

    lines = [
        "## Quality eval — council vs single model + self-consistency",
        "",
        f"_Corpus: {len(res.fixtures)} fixtures, {n_bugs} reasoning bugs · "
        f"council = `{', '.join(res.council_lanes)}` · single = `{res.single_lane}` ×{res.k} "
        f"(self-consistency) · repeats = {len(res.council)} · deterministic scorer, no LLM judge._",
        "",
        "| metric | council | single+SC |",
        "|--------|---------|-----------|",
        f"| recall (bugs caught) | {cell(c_rec)} | {cell(s_rec)} |",
        f"| precision | {cell(c_prec)} | {cell(s_prec)} |",
        f"| false alarms on clean lines (avg) | {c_fpd[0]:.1f} | {s_fpd[0]:.1f} |",
        f"| severity exact (of caught) | {cell(c_sev)} | {cell(s_sev)} |",
        "",
        verdict,
        "",
        _winloss_table(res),
        "",
        "> Directional only — small N. Reproduce on your machine: `cli-bridge eval --live "
        f"--council-lanes {','.join(res.council_lanes)} --single-lane {res.single_lane} "
        f"--k {res.k} --repeats 5`. Numbers depend on your installed CLIs and their current models.",
    ]
    return "\n".join(lines)


def _winloss_table(res: EvalResult) -> str:
    """Per-bug: did the council catch it (in ANY repeat), did single? The honest part — shows
    where each arm wins and loses, not just the aggregate."""
    council_caught: dict[str, bool] = {}
    single_caught: dict[str, bool] = {}
    bug_meta: dict[str, tuple[str, str]] = {}   # bug_id -> (fixture_id, category)
    for fx in res.fixtures:
        for b in fx.bugs:
            bug_meta[b.id] = (fx.id, b.category)
            council_caught.setdefault(b.id, False)
            single_caught.setdefault(b.id, False)
    for run in res.council:
        for s in run.per_fixture.values():
            for bid in s.caught_ids:
                council_caught[bid] = True
    for run in res.single:
        for s in run.per_fixture.values():
            for bid in s.caught_ids:
                single_caught[bid] = True
    rows = ["### Where each arm won / lost (caught in ≥1 repeat)", "",
            "| bug | category | council | single+SC |",
            "|-----|----------|:------:|:--------:|"]
    for bid in sorted(bug_meta):
        fx_id, cat = bug_meta[bid]
        cc = "✅" if council_caught.get(bid) else "❌"
        ss = "✅" if single_caught.get(bid) else "❌"
        rows.append(f"| {fx_id}/{bid} | {cat} | {cc} | {ss} |")
    return "\n".join(rows)


def result_dict(res: EvalResult) -> dict:
    def arm(runs: list[ArmRun]) -> dict:
        return {
            "recall": [round(r.recall, 4) for r in runs],
            "precision": [round(r.precision, 4) for r in runs],
            "fp_decoy": [r.fp_decoy for r in runs],
            "fp_other": [r.fp_other for r in runs],
            "sev_acc": [round(r.sev_acc, 4) for r in runs],
            "tp": [r.tp for r in runs],
            "n_bugs": [r.n_bugs for r in runs],
        }
    return {
        "tool": "eval",
        "council_lanes": res.council_lanes,
        "single_lane": res.single_lane,
        "k": res.k,
        "repeats": len(res.council),
        "council": arm(res.council),
        "single": arm(res.single),
        "corpus": corpus_summary(res.fixtures),
    }
