"""Terse preamble: levels, toggle, English, reason-fully, code-safe, no-op when off."""
from cli_bridge import preamble


def test_default_is_lite(monkeypatch):
    monkeypatch.delenv("CLI_BRIDGE_TERSE", raising=False)
    assert preamble.level() == "lite"


def test_off_is_noop(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_TERSE", "off")
    assert preamble.preamble() == ""
    assert preamble.apply("hello") == "hello"


def test_levels(monkeypatch):
    for lvl in ("lite", "full", "ultra"):
        monkeypatch.setenv("CLI_BRIDGE_TERSE", lvl.upper())
        assert preamble.level() == lvl
        assert preamble.apply("Q") .endswith("Q")
        assert preamble.preamble()  # non-empty


def test_invalid_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_TERSE", "garbage")
    assert preamble.level() == "lite"   # unknown value -> safe default


def test_full_preamble_has_key_directives(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_TERSE", "full")
    p = preamble.preamble()
    assert "English" in p                  # language pinned
    assert "reason FULLY" in p.replace("Reason", "reason")  # reasoning preserved
    assert "UNCHANGED" in p                 # code/JSON safe
    assert "safety" in p.lower()            # auto-clarity exception


def test_apply_prepends_then_task(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_TERSE", "full")
    out = preamble.apply("THE_TASK")
    assert out.endswith("THE_TASK") and out.startswith("[response style]")


def test_lite_is_shorter_than_full(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_TERSE", "lite")
    lite = preamble.preamble()
    monkeypatch.setenv("CLI_BRIDGE_TERSE", "full")
    full = preamble.preamble()
    assert 0 < len(lite) < len(full)        # lite trimmed to a low fixed overhead
    assert len(lite) < 220                  # ~38 tokens of fixed input cost


def test_lite_keeps_english_and_exactness(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_TERSE", "lite")
    p = preamble.preamble()
    assert "English" in p and "exact" in p and "Reason fully" in p


def test_min_chars_skips_preamble_on_tiny_task(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_TERSE", "lite")
    monkeypatch.setenv("CLI_BRIDGE_TERSE_MIN_CHARS", "50")
    assert preamble.apply("short q") == "short q"          # below threshold -> no preamble
    long_task = "x" * 60
    assert preamble.apply(long_task).startswith("[response style]")  # above -> prefixed


def test_min_chars_default_never_skips(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_TERSE", "lite")
    monkeypatch.delenv("CLI_BRIDGE_TERSE_MIN_CHARS", raising=False)
    assert preamble.apply("q").startswith("[response style]")        # 0 = never skip
