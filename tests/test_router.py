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
    assert "gpt" not in keys and "claude" not in keys      # limited excluded
    assert {"gemini", "mistral", "opencode"} <= keys


def test_cooled_lane_sinks_to_bottom():
    def cooled(key):
        return 999 if key == "gemini" else 0
    order = router.order_lanes(_builtins(), cooled, include_paid=False)
    assert order[-1].key == "gemini"                       # cooled but still present, last


def test_priority_env_overrides_within_tier(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_MISTRAL_PRIORITY", "1")  # lower = earlier
    order = router.order_lanes(_builtins(), _no_cooldown, include_paid=False)
    free = [l.key for l in order if l.cost_label == "free"]
    assert free[0] == "mistral"


def test_explain_lists_order():
    txt = router.explain(_builtins(), _no_cooldown, include_paid=False)
    assert "Cascade order" in txt and "gemini" in txt


def test_explain_empty_when_nothing_eligible():
    txt = router.explain([], _no_cooldown, include_paid=False)
    assert "No eligible lanes" in txt
