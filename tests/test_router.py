"""Phase 3: deterministic cascade ordering, cooldown-aware, profile-aware."""
from cli_bridge import lanes, router


def _builtins():
    return list(lanes.BUILTIN_LANES)


def _no_cooldown(_key):
    return 0


def test_free_before_limited_before_paid():
    order = router.order_lanes(_builtins(), _no_cooldown, include_paid=True)
    ranks = [router._COST_RANK[l.cost_label] for l in order]
    assert ranks == sorted(ranks)                         # monotonic free→limited→paid
    assert order[0].cost_label == "free"


def test_excludes_paid_and_limited_by_default():
    order = router.order_lanes(_builtins(), _no_cooldown, include_paid=False)
    assert all(l.cost_label == "free" for l in order)
    keys = {l.key for l in order}
    assert keys.isdisjoint({"gpt", "claude", "mistral"})   # limited excluded
    assert {"gemini", "opencode"} <= keys


def test_cooled_lane_sinks_to_bottom():
    def cooled(key):
        return 999 if key == "gemini" else 0
    order = router.order_lanes(_builtins(), cooled, include_paid=False)
    assert order[-1].key == "gemini"                       # cooled but still present, last


def test_priority_env_overrides_within_tier(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_OPENCODE_PRIORITY", "1")  # lower = earlier
    order = router.order_lanes(_builtins(), _no_cooldown, include_paid=False)
    free = [l.key for l in order if l.cost_label == "free"]
    assert free[0] == "opencode"


def test_explain_lists_order():
    txt = router.explain(_builtins(), _no_cooldown, include_paid=False)
    assert "Cascade order" in txt and "gemini" in txt


def test_explain_empty_when_nothing_eligible():
    txt = router.explain([], _no_cooldown, include_paid=False)
    assert "No eligible lanes" in txt


# ── ask_best mode ordering (M6) ───────────────────────────────────────────────────────────

def _no_perf(_key):
    return {}


def test_cheap_mode_excludes_limited_and_paid():
    order = router.order_for_mode(_builtins(), _no_cooldown, _no_perf, "cheap", include_paid=True)
    # cheap mode is free-only regardless of include_paid
    assert all(l.cost_label == "free" for l in order)


def test_deep_mode_allows_paid_only_when_included():
    free_only = router.order_for_mode(_builtins(), _no_cooldown, _no_perf, "deep",
                                      include_paid=False)
    assert all(l.cost_label == "free" for l in free_only)        # ceiling = cost policy
    widened = router.order_for_mode(_builtins(), _no_cooldown, _no_perf, "deep",
                                    include_paid=True)
    assert any(l.is_paid or l.is_limited for l in widened)


def test_fast_mode_prefers_lower_measured_latency():
    perf = {"gemini": {"runs": 5, "avg_ms": 9000, "fail_rate": 0.0},
            "opencode": {"runs": 5, "avg_ms": 200, "fail_rate": 0.0}}
    order = router.order_for_mode(_builtins(), _no_cooldown, lambda k: perf.get(k, {}),
                                  "fast", include_paid=False)
    free = [l.key for l in order if l.cost_label == "free"]
    assert free.index("opencode") < free.index("gemini")          # faster lane first


def test_capability_mode_prefers_effort_capable():
    order = router.order_for_mode(_builtins(), _no_cooldown, _no_perf, "code", include_paid=True)
    # the first lane should advertise the 'effort' capability (a deep-thinking proxy)
    assert "effort" in order[0].caps


def test_cooled_lane_sinks_in_mode_order():
    def cooled(key):
        return 999 if key == "opencode" else 0
    order = router.order_for_mode(_builtins(), cooled, _no_perf, "cheap", include_paid=False)
    assert order[-1].key == "opencode"


def test_explain_mode_text():
    txt = router.explain_mode(_builtins(), _no_cooldown, _no_perf, "fast", include_paid=False)
    assert "Mode 'fast'" in txt and "latency" in txt
