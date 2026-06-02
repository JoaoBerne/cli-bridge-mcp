"""Cost profile + onboarding: no preset is imposed, the assistant configures to the user."""
from cli_bridge import server


def test_profile_defaults_balanced(monkeypatch):
    monkeypatch.delenv("CLI_BRIDGE_PROFILE", raising=False)
    assert server._profile() == "balanced"
    assert server._profile_is_set() is False


def test_profile_valid_values(monkeypatch):
    for p in ("saver", "balanced", "max"):
        monkeypatch.setenv("CLI_BRIDGE_PROFILE", p.upper())  # case-insensitive
        assert server._profile() == p
        assert server._profile_is_set() is True


def test_profile_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_PROFILE", "garbage")
    assert server._profile() == "balanced"
    assert server._profile_is_set() is False


def test_setup_text_is_conversational_not_a_locked_menu():
    # must guide an actual conversation, not force one of N presets
    assert "doctor" in server.SETUP_TEXT
    assert "EACH installed lane" in server.SETUP_TEXT
    assert "CLI_BRIDGE_<LANE>_COST" in server.SETUP_TEXT
    assert "limited" in server.SETUP_TEXT


def test_instructions_tell_host_to_ask():
    assert "setup" in server.INSTRUCTIONS
    assert "free is best" in server.INSTRUCTIONS  # explicitly warns against the assumption


def test_instructions_cover_the_new_capabilities():
    # the host must be told it can hold a round-table and delegate work safely
    instr = server.INSTRUCTIONS.lower()
    assert "round-table" in instr or "conversation" in instr
    assert "ask_build_isolated" in server.INSTRUCTIONS
    assert "when not to" in instr          # the "don't convene for one-liners" guardrail


def test_setup_recommends_a_concrete_config(monkeypatch):
    from cli_bridge.lanes import LaneSpec
    monkeypatch.delenv("CLI_BRIDGE_PROFILE", raising=False)
    free = LaneSpec("gemini", "Gemini", "echo", lambda *x: [], cost_default="free")
    paid = LaneSpec("op", "OP", "echo", lambda *x: [], cost_default="paid")
    rec = server._setup_recommendation([free, paid])
    assert "gemini" in rec and "op" in rec       # lanes classified
    assert "Recommended" in rec and "CLI_BRIDGE_PROFILE" in rec
    assert "CLI_BRIDGE_DAILY_CREDIT_CAP" in rec  # a paid lane present -> recommend a cap


def test_setup_recommendation_handles_no_lanes():
    assert "No delegate CLIs" in server._setup_recommendation([])
