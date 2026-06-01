"""P0-3: opencode free-model lookup uses a TTL cache that can recover, not lru_cache."""

from cli_bridge import lanes


def test_ttl_cache_recovers_after_failure(monkeypatch):
    """A transient empty result must NOT be cached forever (the lru_cache bug)."""
    lanes._opencode_model_cache.clear()
    calls = {"n": 0}

    def fake_run(argv, **kw):
        calls["n"] += 1
        class R:
            returncode = 0 if calls["n"] >= 2 else 1   # first call fails, then succeeds
            stdout = "opencode/deepseek-v4-flash-free\nopencode-go/pro\n"
        return R()

    monkeypatch.setattr(lanes.subprocess, "run", fake_run)
    assert lanes._current_opencode_free_model("opencode") == ""        # 1st: failure, not cached
    assert lanes._current_opencode_free_model("opencode") == "opencode/deepseek-v4-flash-free"
    assert calls["n"] == 2                                              # re-probed (no stale cache)


def test_positive_result_is_cached(monkeypatch):
    lanes._opencode_model_cache.clear()
    calls = {"n": 0}

    def fake_run(argv, **kw):
        calls["n"] += 1
        class R:
            returncode = 0
            stdout = "opencode/deepseek-v4-flash-free\n"
        return R()

    monkeypatch.setattr(lanes.subprocess, "run", fake_run)
    a = lanes._current_opencode_free_model("opencode")
    b = lanes._current_opencode_free_model("opencode")               # within TTL -> cached
    assert a == b == "opencode/deepseek-v4-flash-free"
    assert calls["n"] == 1


def test_ttl_expiry_reprobes(monkeypatch):
    lanes._opencode_model_cache.clear()
    monkeypatch.setattr(lanes, "_OPENCODE_MODEL_TTL_S", 0)            # everything is stale
    calls = {"n": 0}

    def fake_run(argv, **kw):
        calls["n"] += 1
        class R:
            returncode = 0
            stdout = "opencode/deepseek-v4-flash-free\n"
        return R()

    monkeypatch.setattr(lanes.subprocess, "run", fake_run)
    lanes._current_opencode_free_model("opencode")
    lanes._current_opencode_free_model("opencode")
    assert calls["n"] == 2                                            # TTL=0 -> re-probe each time
