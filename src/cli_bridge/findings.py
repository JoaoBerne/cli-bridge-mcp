"""Structured review findings — pure, no I/O, fully unit-testable.

Each reviewer is asked for a JSON array of findings. We parse it tolerantly (a model that
wraps JSON in prose or fences, or ignores the format entirely, must never crash the review —
its text is wrapped as one fallback finding so nothing is silently dropped). Findings are then
merged deterministically by (file, line, normalized title): duplicates collapse, the models
that raised each one accumulate, and confidence is derived from how many distinct models agree
(single / majority / consensus). Rendered to Markdown (PR-comment friendly) or a JSON result.

Deterministic merge replaces an LLM "merge pass": cheaper, reproducible, and it can't invent
findings that no reviewer actually raised.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace

# Severity scale, strongest first. _SEV_RANK orders output; aliases map common model wording.
SEVERITIES = ("blocker", "high", "medium", "low", "info")
_SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
_SEV_ALIASES = {
    "critical": "blocker", "crit": "blocker", "fatal": "blocker", "severe": "blocker",
    "major": "high", "important": "high",
    "moderate": "medium", "med": "medium", "warning": "medium", "warn": "medium",
    "minor": "low", "nit": "low",
    "note": "info", "informational": "info", "suggestion": "info",
}
_DEFAULT_SEVERITY = "medium"

STATIC_SOURCE = "static-check"   # label for deterministic precheck findings


@dataclass
class Finding:
    severity: str
    title: str
    file: str | None = None
    line: int | None = None
    evidence: str = ""
    recommendation: str = ""
    models: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)


# ── severity / value coercion ───────────────────────────────────────────────────────────

def normalize_severity(raw) -> str:
    s = str(raw or "").strip().lower()
    s = _SEV_ALIASES.get(s, s)
    return s if s in _SEV_RANK else _DEFAULT_SEVERITY


def _clean_str(v) -> str:
    return "" if v is None else str(v).strip()


def _opt_str(v) -> str | None:
    s = _clean_str(v)
    return None if s == "" or s.lower() in {"null", "none", "n/a"} else s


def _opt_int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


# ── tolerant JSON extraction ──────────────────────────────────────────────────────────────

def _strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\n?", "", t)
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def _try_load(s: str):
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def _extract(text: str):
    """Best-effort parse of the largest JSON array/object in a model's reply. Returns the
    decoded value or None."""
    t = _strip_fence(text)
    data = _try_load(t)
    if data is not None:
        return data
    # Model added prose around the JSON: slice from the first bracket to its last partner.
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i, j = t.find(open_c), t.rfind(close_c)
        if 0 <= i < j:
            data = _try_load(t[i:j + 1])
            if data is not None:
                return data
    return None


def _items(data) -> list | None:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("findings", "issues", "results"):
            if isinstance(data.get(key), list):
                return data[key]
        if any(k in data for k in ("severity", "title", "issue", "problem")):
            return [data]          # a single bare finding object
    return None


_NO_ISSUES_RE = re.compile(r"\bno\b.{0,40}\b(issue|finding|problem|vulnerab)", re.IGNORECASE)


def _coerce(item, role: str, lane: str) -> Finding | None:
    if not isinstance(item, dict):
        return None
    title = _clean_str(item.get("title") or item.get("issue") or item.get("problem"))
    evidence = _clean_str(item.get("evidence") or item.get("problem") or item.get("description"))
    if not title:
        title = (evidence.splitlines()[0][:80] if evidence else "(untitled finding)")
    return Finding(
        severity=normalize_severity(item.get("severity")),
        title=title,
        file=_opt_str(item.get("file") or item.get("path")),
        line=_opt_int(item.get("line")),
        evidence=evidence,
        recommendation=_clean_str(item.get("recommendation") or item.get("fix")
                                  or item.get("remediation")),
        models=[lane],
        roles=[role],
    )


def parse_findings(text: str, *, role: str, lane: str) -> tuple[list[Finding], bool]:
    """(findings, parsed_ok). parsed_ok=False means the reply wasn't valid findings JSON, so
    the raw text is wrapped as ONE medium finding (never silently dropped). An explicit empty
    array or a 'no issues' reply is a clean parse with zero findings."""
    data = _extract(text or "")
    items = _items(data)
    if items is None:
        if not (text or "").strip() or _NO_ISSUES_RE.search(text or ""):
            return [], True
        snippet = (text or "").strip()
        return [Finding(severity=_DEFAULT_SEVERITY,
                        title=f"Unparsed {role} review (could not read as JSON)",
                        evidence=snippet[:600], models=[lane], roles=[role])], False
    out = [f for f in (_coerce(it, role, lane) for it in items) if f is not None]
    return out, True


# ── deterministic merge ─────────────────────────────────────────────────────────────────

def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _merge_key(f: Finding) -> tuple:
    return (f.file or "", f.line if f.line is not None else -1, _norm_title(f.title))


def merge_findings(findings: list[Finding]) -> list[Finding]:
    """Collapse duplicates by (file, line, normalized title). The merged entry keeps the
    strongest severity, unions models+roles, and keeps the longest evidence/recommendation.
    Sorted strongest-severity first, then by file/line for stable output."""
    groups: dict[tuple, Finding] = {}
    for f in findings:
        k = _merge_key(f)
        g = groups.get(k)
        if g is None:
            groups[k] = replace(f, models=list(f.models), roles=list(f.roles))
            continue
        if _SEV_RANK[f.severity] < _SEV_RANK[g.severity]:
            g.severity = f.severity
        for m in f.models:
            if m not in g.models:
                g.models.append(m)
        for r in f.roles:
            if r not in g.roles:
                g.roles.append(r)
        if len(f.evidence) > len(g.evidence):
            g.evidence = f.evidence
        if len(f.recommendation) > len(g.recommendation):
            g.recommendation = f.recommendation
    return sorted(groups.values(),
                  key=lambda f: (_SEV_RANK[f.severity], f.file or "~", f.line or 0, f.title))


def confidence(f: Finding, total_reviewers: int) -> str:
    """single / majority / consensus from how many distinct models raised the finding."""
    n = len(f.models)
    if total_reviewers <= 1:
        return "single"
    if n >= total_reviewers:
        return "consensus"
    return "majority" if n >= 2 else "single"


def verdict(findings: list[Finding]) -> str:
    sev = {f.severity for f in findings}
    if "blocker" in sev:
        return "block — blocker-level issues must be fixed before merge"
    if "high" in sev:
        return "fix-first — high-severity issues should be resolved before merge"
    if findings:
        return "ship with nits — only medium/low issues remain"
    return "ship — no issues found"


# ── rendering ───────────────────────────────────────────────────────────────────────────

def _counts(findings: list[Finding]) -> str:
    by = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}
    return ", ".join(f"{by[s]} {s}" for s in SEVERITIES if by[s])


def render_markdown(findings: list[Finding], *, total_reviewers: int, heading: str,
                    meta: dict, recap: str = "", residual_risk: str = "") -> str:
    lines = [f"# {heading}", ""]
    flags = (["diff truncated"] if meta.get("truncated") else []) + ["read-only"]
    lines.append(f"_Base: `{meta.get('base', 'HEAD')}` · reviewers: "
                 f"{', '.join(meta.get('reviewers', []))} · {' · '.join(flags)}_\n")
    if recap:
        lines.append(recap)
        lines.append("")
    n = len(findings)
    lines.append(f"**{n} finding{'s' if n != 1 else ''}**"
                 + (f" ({_counts(findings)})" if findings else "") + f" — _{verdict(findings)}_\n")
    if not findings:
        lines.append("No issues raised by any reviewer.")
    cur = None
    for f in findings:
        if f.severity != cur:
            cur = f.severity
            lines.append(f"\n## {cur.capitalize()}\n")
        loc = f" `{f.file}{':' + str(f.line) if f.line is not None else ''}`" if f.file else ""
        models = ", ".join(f.models) if f.models else "?"
        lines.append(f"- **{f.title}**{loc} — _{confidence(f, total_reviewers)}_ · {models}")
        if f.evidence:
            lines.append(f"  {f.evidence}")
        if f.recommendation:
            lines.append(f"  **Fix:** {f.recommendation}")
    if residual_risk:
        lines.append(f"\n## Residual risk\n\n{residual_risk}")
    lines.append("\n## Trace\n```json\n" + json.dumps(meta, indent=2) + "\n```")
    return "\n".join(lines)


def result_json(findings: list[Finding], *, total_reviewers: int, tool: str, summary: str,
                meta: dict, residual_risk: str = "") -> dict:
    return {
        "tool": tool,
        "status": "ok",
        "summary": summary,
        "verdict": verdict(findings),
        "findings": [
            {
                "id": f"F{i + 1:03d}",
                "severity": f.severity,
                "confidence": confidence(f, total_reviewers),
                "title": f.title,
                "file": f.file,
                "line": f.line,
                "models": f.models,
                "evidence": f.evidence,
                "recommendation": f.recommendation,
            }
            for i, f in enumerate(findings)
        ],
        "residual_risk": residual_risk,
        "meta": meta,
    }
