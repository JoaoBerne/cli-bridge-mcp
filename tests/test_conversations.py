"""Round-table conversation store + recipient-aware transcript replay.

No network, no real CLI — exercises the sqlite-backed turn store and the dual-phase,
recipient-aware history reconstruction that makes a multi-lane thread coherent.
"""
import pytest

from cli_bridge import conversations, telemetry


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "s.sqlite"))
    telemetry._reset_for_tests()
    yield
    telemetry._reset_for_tests()


def test_empty_history_no_prefix():
    # First turn of any thread: no prior history -> behaves like a plain one-shot ask.
    prefix, trimmed = conversations.build_history_prefix("ghost", "gemini", 32000)
    assert prefix == "" and trimmed is False


def test_roundtable_attribution_and_chronology():
    cid = conversations.new_id()
    conversations.record_turn(cid, "gemini", "user", "Explain quicksort")
    conversations.record_turn(cid, "gemini", "assistant", "Quicksort partitions around a pivot.")
    conversations.record_turn(cid, "gpt", "user", "Do you agree with what gemini said?")
    conversations.record_turn(cid, "gpt", "assistant", "Mostly, but watch the worst-case O(n^2).")

    # Re-asking gemini: its own reply is "You", gpt's is "gpt", host prompts are "User".
    pg, trimmed = conversations.build_history_prefix(cid, "gemini", 32000)
    assert not trimmed
    assert "--- You ---" in pg          # gemini's own earlier turn
    assert "--- gpt ---" in pg          # the other lane, named
    assert "--- User ---" in pg         # the host's prompts
    # chronological: the pivot answer (turn 2) comes before gpt's worst-case note (turn 4)
    assert pg.index("partitions around a pivot") < pg.index("worst-case")

    # From gpt's view, attribution flips: gpt's reply is "You", gemini's is "gemini".
    pgpt, _ = conversations.build_history_prefix(cid, "gpt", 32000)
    assert "--- You ---" in pgpt and "--- gemini ---" in pgpt


def test_sliding_window_drops_oldest_keeps_newest():
    cid = conversations.new_id()
    for i in range(20):
        conversations.record_turn(cid, "gemini", "assistant", f"answer-{i} " + "x" * 500)
    prefix, trimmed = conversations.build_history_prefix(cid, "gemini", 2000)
    assert trimmed
    assert "answer-19" in prefix          # newest kept
    assert "answer-0" not in prefix       # oldest dropped
    assert "earlier turns omitted" in prefix
    assert len(prefix) < 3500             # far below the untrimmed ~10k


def test_newest_turn_kept_even_if_over_budget():
    cid = conversations.new_id()
    conversations.record_turn(cid, "gemini", "assistant", "Z" * 5000)
    prefix, trimmed = conversations.build_history_prefix(cid, "gemini", 1000)
    assert "ZZZ" in prefix                # the single newest turn is never dropped to nothing


def test_is_valid_id():
    assert conversations.is_valid_id("ab12cd34")
    assert conversations.is_valid_id("my-thread_1")
    assert not conversations.is_valid_id("")
    assert not conversations.is_valid_id("bad id!")
    assert not conversations.is_valid_id("x" * 65)


def test_log_mirror_writes_readable_markdown(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_CONVO_LOG_DIR", str(tmp_path / "logs"))
    cid = conversations.new_id()
    conversations.record_turn(cid, "gemini", "user", "the question")
    conversations.record_turn(cid, "gemini", "assistant", "the answer")
    md = (tmp_path / "logs" / f"{cid}.md").read_text()
    assert "### User" in md and "the question" in md
    assert "### gemini" in md and "the answer" in md


def test_list_recovers_threads_after_reset():
    a, b = conversations.new_id(), conversations.new_id()
    conversations.record_turn(a, "gemini", "user", "thread A q")
    conversations.record_turn(a, "gemini", "assistant", "thread A answer")
    conversations.record_turn(b, "gpt", "user", "thread B q")
    listing = telemetry.convo_list()
    ids = {c["conversation_id"] for c in listing}
    assert a in ids and b in ids
    rec_a = next(c for c in listing if c["conversation_id"] == a)
    assert rec_a["turns"] == 2 and rec_a["lanes"] == ["gemini"]
