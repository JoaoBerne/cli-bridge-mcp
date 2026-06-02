"""Round-table conversations — multi-turn, multi-lane threads via transcript replay.

A spawned CLI is one-shot: it answers and dies, holding no session. And no single CLI's
native memory can hold a *cross-model* discussion (Gemini's session can't contain what GPT
said). So the shared transcript has to live with us: cli-bridge stores every turn locally
(sqlite, via telemetry) and replays a recipient-aware, budget-bounded history before each
new turn. The lane "remembers" only because we hand it the transcript.

Because the store is sqlite (not in-process), a thread survives the host's context
compaction (`/compact`) AND a server restart — the host can `conversations_list` to recover
a thread id and pick up where it left off.

Pure logic + thin telemetry calls; no import of server.py, so server.py stays thin.
"""
from __future__ import annotations

import os
import uuid

from . import config, telemetry

_HEADER = (
    "=== ROUND-TABLE CONVERSATION (continuation) ===\n"
    "Below is the prior exchange between you and other AI assistants on this thread. "
    "Turns marked '--- You ---' are your own earlier replies; other assistants are named; "
    "'--- User ---' is the person you're all helping.\n"
)
_OMITTED = "[... earlier turns omitted to fit the context budget ...]\n"
_FOOTER = "\n=== NEW INPUT (continue the thread; reply as the assistant) ==="


def new_id() -> str:
    """A short, unique thread id (8 hex chars)."""
    return uuid.uuid4().hex[:8]


def is_valid_id(conversation_id: str) -> bool:
    """Accept our ids and any sane host-supplied token (alnum/_/-, <=64). Rejects junk early so
    a bad id can't reach storage."""
    cid = (conversation_id or "").strip()
    return bool(cid) and len(cid) <= 64 and all(c.isalnum() or c in "-_" for c in cid)


def record_turn(conversation_id: str, lane: str, role: str, content: str) -> int:
    """Append one turn (role='user' for the host's prompt, 'assistant' for a lane's reply).
    Returns the turn number (0 if telemetry is off). Stores the RAW text — never the
    history-augmented prompt — so replays don't nest and explode."""
    n = telemetry.convo_append(conversation_id, lane, role, content)
    _mirror_log(conversation_id, lane, role, content)
    return n


def _mirror_log(conversation_id: str, lane: str, role: str, content: str) -> None:
    """If CLI_BRIDGE_CONVO_LOG_DIR is set, append the turn to a readable <id>.md transcript —
    a human-friendly mirror of the sqlite store, handy to re-read a round-table after a
    /compact. Best-effort: never raises into a delegation."""
    d = config.convo_log_dir()
    if not d:
        return
    who = "User" if role == "user" else (lane or "assistant")
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{conversation_id}.md"), "a", encoding="utf-8") as fh:
            fh.write(f"\n### {who}\n\n{content}\n")
    except OSError:
        pass


def _render_turn(turn: dict, recipient_lane: str) -> str:
    role = turn.get("role")
    lane = turn.get("lane") or ""
    if role == "user":
        speaker = "User"
    elif lane and lane == recipient_lane:
        speaker = "You"
    else:
        speaker = lane or "Assistant"
    return f"--- {speaker} ---\n{turn.get('content', '')}"


def build_history_prefix(conversation_id: str, recipient_lane: str,
                         max_chars: int) -> tuple[str, bool]:
    """Build the recipient-aware transcript to prepend before the next turn to `recipient_lane`.

    Dual-phase windowing (the technique zen uses): collect turns newest-first until the char
    budget is hit (so recent context is always kept), then present them chronologically (so the
    model reads a natural conversation). The recipient's own past turns are marked 'You', other
    lanes by name. The newest turn is always included even if it alone exceeds the budget.

    Returns (prefix, trimmed). When there's no prior history, returns ("", False) so the very
    first turn behaves exactly like a normal one-shot ask (zero regression).
    """
    turns = telemetry.convo_turns(conversation_id)
    if not turns:
        return "", False

    collected: list[str] = []      # newest-first
    used = 0
    trimmed = False
    for turn in reversed(turns):
        line = _render_turn(turn, recipient_lane)
        if collected and used + len(line) > max_chars:
            trimmed = True
            break
        collected.append(line)
        used += len(line)

    collected.reverse()            # back to chronological
    header = _HEADER + (_OMITTED if trimmed else "")
    body = "\n\n".join(collected)
    return f"{header}\n{body}{_FOOTER}", trimmed
