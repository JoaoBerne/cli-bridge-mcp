"""Structured findings: tolerant parse, deterministic merge, confidence, render + JSON."""
import json

from cli_bridge import findings
from cli_bridge.findings import Finding

# ── severity normalization ──────────────────────────────────────────────────────────────

def test_normalize_severity_aliases_and_default():
    assert findings.normalize_severity("CRITICAL") == "blocker"
    assert findings.normalize_severity("major") == "high"
    assert findings.normalize_severity("nit") == "low"
    assert findings.normalize_severity("warning") == "medium"
    assert findings.normalize_severity("") == "medium"        # unknown -> safe default
    assert findings.normalize_severity("bogus") == "medium"


# ── parsing ─────────────────────────────────────────────────────────────────────────────

def test_parse_clean_array():
    txt = '[{"severity":"high","title":"SQLi","file":"db.py","line":10,' \
          '"evidence":"concat","recommendation":"parameterize"}]'
    fs, ok = findings.parse_findings(txt, role="security", lane="Gemini")
    assert ok and len(fs) == 1
    f = fs[0]
    assert (f.severity, f.title, f.file, f.line) == ("high", "SQLi", "db.py", 10)
    assert f.models == ["Gemini"] and f.roles == ["security"]


def test_parse_strips_markdown_fence():
    txt = '```json\n[{"severity":"low","title":"naming"}]\n```'
    fs, ok = findings.parse_findings(txt, role="maint", lane="X")
    assert ok and fs[0].title == "naming" and fs[0].severity == "low"


def test_parse_prose_wrapped_json():
    txt = 'Sure, here are my findings:\n[{"severity":"medium","title":"edge case"}]\nHope this helps!'
    fs, ok = findings.parse_findings(txt, role="correctness", lane="X")
    assert ok and fs[0].title == "edge case"


def test_parse_findings_key_object():
    txt = '{"findings":[{"severity":"high","title":"A"},{"severity":"low","title":"B"}]}'
    fs, ok = findings.parse_findings(txt, role="r", lane="L")
    assert ok and [f.title for f in fs] == ["A", "B"]


def test_parse_single_bare_object():
    fs, ok = findings.parse_findings('{"severity":"high","title":"lone"}', role="r", lane="L")
    assert ok and len(fs) == 1 and fs[0].title == "lone"


def test_parse_empty_array_is_clean():
    fs, ok = findings.parse_findings("[]", role="r", lane="L")
    assert ok and fs == []


def test_parse_no_issues_sentinel():
    fs, ok = findings.parse_findings("No security issues found.", role="security", lane="L")
    assert ok and fs == []


def test_parse_garbage_falls_back_without_crash():
    fs, ok = findings.parse_findings("the code looks risky to me, no JSON here", role="x", lane="L")
    assert ok is False and len(fs) == 1
    assert "Unparsed" in fs[0].title and fs[0].severity == "medium"
    assert "risky" in fs[0].evidence


def test_parse_field_aliases():
    txt = '[{"severity":"high","issue":"bug","problem":"why","fix":"do this"}]'
    fs, ok = findings.parse_findings(txt, role="r", lane="L")
    f = fs[0]
    assert f.title == "bug" and f.evidence == "why" and f.recommendation == "do this"


def test_parse_null_file_line():
    fs, _ = findings.parse_findings('[{"severity":"low","title":"t","file":"null","line":"n/a"}]',
                                    role="r", lane="L")
    assert fs[0].file is None and fs[0].line is None


# ── merge + confidence ──────────────────────────────────────────────────────────────────

def test_merge_dedupes_and_unions_models():
    a = Finding("medium", "Same Bug", "f.py", 5, "ev1", "fix1", ["Gemini"], ["correctness"])
    b = Finding("high", "same bug", "f.py", 5, "ev2 longer", "", ["Mistral"], ["security"])
    merged = findings.merge_findings([a, b])
    assert len(merged) == 1
    m = merged[0]
    assert m.severity == "high"                       # strongest wins
    assert set(m.models) == {"Gemini", "Mistral"}
    assert m.evidence == "ev2 longer"                 # longest kept
    assert m.recommendation == "fix1"                 # longest non-empty kept


def test_merge_keeps_distinct_locations():
    a = Finding("low", "T", "a.py", 1)
    b = Finding("low", "T", "b.py", 1)
    assert len(findings.merge_findings([a, b])) == 2


def test_merge_fuzzy_same_location_similar_titles():
    # same file:line, same bug worded differently -> ONE merged finding
    a = Finding("high", "SQL injection in user query", "db.py", 42, models=["Gemini"])
    b = Finding("high", "SQL injection in the user query builder", "db.py", 42, models=["Mistral"])
    merged = findings.merge_findings([a, b])
    assert len(merged) == 1 and set(merged[0].models) == {"Gemini", "Mistral"}


def test_merge_fuzzy_needs_concrete_location():
    # similar titles but NO file/line -> NOT fuzzy-merged (can't safely anchor)
    a = Finding("medium", "Unparsed correctness review could not read as json", models=["A"])
    b = Finding("medium", "Unparsed security review could not read as json", models=["B"])
    assert len(findings.merge_findings([a, b])) == 2


def test_merge_dissimilar_titles_same_location_kept():
    a = Finding("high", "SQL injection", "db.py", 42)
    b = Finding("low", "Missing docstring", "db.py", 42)
    assert len(findings.merge_findings([a, b])) == 2


def test_merge_sorts_strongest_first():
    fs = [Finding("low", "z"), Finding("blocker", "a"), Finding("medium", "m")]
    out = [f.severity for f in findings.merge_findings(fs)]
    assert out == ["blocker", "medium", "low"]


def test_confidence_levels():
    f1 = Finding("high", "t", models=["A"])
    f2 = Finding("high", "t", models=["A", "B"])
    f3 = Finding("high", "t", models=["A", "B", "C"])
    assert findings.confidence(f1, total_reviewers=1) == "single"     # only one source
    assert findings.confidence(f1, total_reviewers=3) == "single"
    assert findings.confidence(f2, total_reviewers=3) == "majority"
    assert findings.confidence(f3, total_reviewers=3) == "consensus"


def test_verdict():
    assert findings.verdict([]) .startswith("ship")
    assert findings.verdict([Finding("low", "x")]).startswith("ship with nits")
    assert findings.verdict([Finding("high", "x")]).startswith("fix-first")
    assert findings.verdict([Finding("blocker", "x")]).startswith("block")


# ── rendering ───────────────────────────────────────────────────────────────────────────

def _meta():
    return {"base": "HEAD", "reviewers": ["security (Gemini)"], "roles_failed": [],
            "truncated": False, "diff_chars": 100}


def test_render_markdown_groups_and_trace():
    fs = [Finding("blocker", "RCE", "x.py", 9, "evil", "sanitize", ["Gemini", "Mistral"])]
    out = findings.render_markdown(fs, total_reviewers=2, heading="Code review", meta=_meta(),
                                   residual_risk="be careful")
    assert "# Code review" in out
    assert "## Blocker" in out and "**RCE**" in out and "`x.py:9`" in out
    assert "consensus" in out and "Gemini, Mistral" in out
    assert "**Fix:** sanitize" in out
    assert "## Residual risk" in out and "be careful" in out
    trace = json.loads(out.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert trace["base"] == "HEAD"


def test_render_no_findings():
    out = findings.render_markdown([], total_reviewers=2, heading="H", meta=_meta())
    assert "0 findings" in out and "No issues raised" in out


def test_result_json_schema():
    fs = [Finding("high", "Bug", "f.py", 3, "ev", "fix", ["Gemini"])]
    res = findings.result_json(fs, total_reviewers=1, tool="review_diff",
                               summary="1 finding", meta=_meta(), residual_risk="r")
    assert res["tool"] == "review_diff" and res["status"] == "ok"
    assert res["findings"][0]["id"] == "F001"
    assert res["findings"][0]["confidence"] == "single"
    assert res["findings"][0]["file"] == "f.py" and res["findings"][0]["line"] == 3
    assert res["residual_risk"] == "r"
    json.dumps(res)   # must be serializable
