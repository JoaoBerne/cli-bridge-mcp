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


def test_instructions_tell_host_to_ask():
    assert "setup" in server.INSTRUCTIONS
    assert "free is best" in server.INSTRUCTIONS  # explicitly warns against the assumption
