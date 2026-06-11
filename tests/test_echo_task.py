"""The '▶ lane — asked: …' echo header on delegation results (CLI_BRIDGE_ECHO_TASK)."""

from cli_bridge import server


def test_header_shows_lane_model_and_task():
    h = server._echo_header("gemini", "gemini-2.5-pro", "find the bug in ./src")
    assert h == '▶ gemini · gemini-2.5-pro — asked: "find the bug in ./src"\n\n'


def test_header_without_model_and_collapses_whitespace():
    h = server._echo_header("ollama", "", "line one\n  line two")
    assert h == '▶ ollama — asked: "line one line two"\n\n'


def test_header_truncates_long_tasks():
    h = server._echo_header("gpt", "", "x" * 500)
    assert '"' + "x" * 140 + '…"' in h


def test_header_disabled_by_env(monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_ECHO_TASK", "off")
    assert server._echo_header("gemini", "m", "task") == ""


def test_header_empty_task_yields_nothing():
    assert server._echo_header("gemini", "m", "") == ""
