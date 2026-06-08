"""Opt-in nested-session env guard: when cli-bridge runs INSIDE a host (Claude Code / Codex) and
spawns that same CLI, the host's session markers can make the child refuse to run. The guard
strips those markers from the delegate's spawn env — but KEEPS auth tokens and the basics, because
it's a function fix, not credential isolation."""
from cli_bridge import config


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("CLI_BRIDGE_STRIP_NESTING_ENV", raising=False)
    assert config.strip_nesting_env() is False


def test_strip_drops_markers_keeps_path_home_and_tokens():
    env = {
        "CLAUDE_CODE_ENTRYPOINT": "cli",     # session marker → dropped
        "CLAUDE_CODE_OAUTH_TOKEN": "secret", # auth token → kept (child must authenticate)
        "CODEX_SANDBOX": "1",                # session marker → dropped
        "PATH": "/usr/bin",                  # basic → kept
        "HOME": "/home/u",                   # basic → kept
        "OPENAI_API_KEY": "sk-xxx",          # api key → kept
        "EDITOR": "vim",                     # unrelated → kept
    }
    out = config.strip_nesting(env)
    assert "CLAUDE_CODE_ENTRYPOINT" not in out
    assert "CODEX_SANDBOX" not in out
    assert out["CLAUDE_CODE_OAUTH_TOKEN"] == "secret"
    assert out["PATH"] == "/usr/bin" and out["HOME"] == "/home/u"
    assert out["OPENAI_API_KEY"] == "sk-xxx" and out["EDITOR"] == "vim"


def test_strip_prefixes_are_configurable(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STRIP_PREFIXES", "GEMINI_")
    env = {"GEMINI_API_KEY": "k", "GEMINI_CLI_SESSION": "s", "CLAUDE_CODE_ENTRYPOINT": "cli"}
    out = config.strip_nesting(env)
    assert "GEMINI_CLI_SESSION" not in out            # custom prefix dropped
    assert out["GEMINI_API_KEY"] == "k"               # api key kept even under a strip prefix
    assert out["CLAUDE_CODE_ENTRYPOINT"] == "cli"     # not a configured prefix anymore → kept


def test_strip_is_pure_does_not_mutate_input():
    env = {"CLAUDE_CODE_ENTRYPOINT": "cli", "PATH": "/bin"}
    config.strip_nesting(env)
    assert "CLAUDE_CODE_ENTRYPOINT" in env            # original untouched
