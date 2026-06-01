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
