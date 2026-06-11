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
import re
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
    if role == "summary":
        speaker = "Summary of earlier turns"
    elif role == "user":
        speaker = "User"
    elif lane and lane == recipient_lane:
        speaker = "You"
    else:
        speaker = lane or "Assistant"
    return f"--- {speaker} ---\n{turn.get('content', '')}"


# ── rolling summary: compact old turns instead of silently dropping them ─────────────────────
# When a thread outgrows the replay budget, the oldest turns used to fall off the window —
# silently forgotten. Instead, the lane that just answered (it had the full history in front
# of it anyway — no third model to route) condenses them into ONE summary turn, so a long
# thread stays usable by ANY lane. Decision logic here is pure; the lane call is the server's.

SUMMARY_PROMPT = (
    "Condense the conversation excerpt below into a faithful summary another AI assistant can "
    "rely on as context. Preserve exactly: decisions made, facts and values stated (names, code "
    "words, numbers, paths), what was asked and what was delivered, and any open points. No "
    "commentary, no praise — just the substance, compact.\n\nEXCERPT:\n")


def compaction_plan(conversation_id: str, max_chars: int) -> tuple[int, str]:
    """If the stored thread exceeds `max_chars`, return (upto_n, excerpt): the oldest turns to
    condense — everything except the newest turns that fit in half the budget (recency is kept
    verbatim; only the old tail is summarized). Returns (0, '') when no compaction is needed.
    An existing summary turn is included in the excerpt so summaries fold into one."""
    turns = telemetry.convo_turns(conversation_id)
    total = sum(len(t.get("content", "")) for t in turns)
    if not turns or total <= max_chars:
        return 0, ""
    keep_budget = max_chars // 2
    used = 0
    cut = 0                                       # index of the first KEPT turn
    for i in range(len(turns) - 1, -1, -1):
        used += len(turns[i].get("content", ""))
        if used > keep_budget:
            cut = i + 1
            break
    if cut < 2:                                   # nothing meaningful to fold — keep as is
        return 0, ""
    old = turns[:cut]
    excerpt = "\n\n".join(_render_turn(t, "") for t in old)
    return int(old[-1]["turn_number"]), excerpt


def apply_compaction(conversation_id: str, upto_n: int, summary: str, lane: str) -> bool:
    """Store the condensed summary in place of the old turns (telemetry, best-effort)."""
    return telemetry.convo_compact(conversation_id, upto_n, summary, lane)


def native_step(ns: dict, conversation_id: str, lane_key: str) -> tuple[list[str], str, int]:
    """Pre-spawn half of native session continuity. Returns (extra_argv, sid, last_seen_turn):
    a known handle → resume argv + the last turn this lane's native session already contains
    (so the prompt replays only the DELTA — turns other lanes added since). No handle yet →
    mint one ourselves (mode=mint) or spawn with the CLI's officially-flagged verbose output
    and capture it after the run (mode=capture)."""
    sid, last = telemetry.convo_session(conversation_id, lane_key)
    if sid and _fold_overlaps(conversation_id, last):
        # Compaction folded turns this lane's native session already holds verbatim — resuming
        # would hand it the summary AGAIN (duplicate context). Drop the handle: this turn runs
        # on a fresh session backed by a full replay (summary included exactly once).
        telemetry.convo_session_drop(conversation_id, lane_key)
        sid, last = "", 0
    if sid:
        return [a.replace("{sid}", sid) for a in ns.get("resume", [])], sid, last
    if ns.get("mode") == "mint":
        sid = str(uuid.uuid4())
        return [a.replace("{sid}", sid) for a in ns.get("first", [])], sid, 0
    return list(ns.get("spawn", [])), "", 0


def _fold_overlaps(conversation_id: str, last_seen: int) -> bool:
    """True when the thread's leading summary turn folds turns the native session has already
    seen verbatim (summary turn_number > last_seen ≥ a folded turn): the delta would duplicate
    context the vendor session already holds."""
    if not last_seen:
        return False
    turns = telemetry.convo_turns(conversation_id)
    return bool(turns) and turns[0].get("role") == "summary" \
        and int(turns[0].get("turn_number", 0)) > last_seen


def native_commit(ns: dict, conversation_id: str, lane_key: str, sid: str,
                  raw_streams: str, last_turn: int) -> None:
    """Post-spawn half: capture the handle from the CLI's output if we don't hold one yet
    (mode=capture), then record handle + high-water turn so the next same-lane turn resumes
    natively and replays only the delta. Best-effort."""
    if not sid and ns.get("pattern"):
        m = re.search(ns["pattern"], raw_streams or "")
        sid = m.group(0) if m else ""
    if sid:
        telemetry.convo_session_set(conversation_id, lane_key, sid, last_turn)


def native_drop(conversation_id: str, lane_key: str) -> None:
    """A resume turn failed — forget the handle; the next turn falls back to full replay."""
    telemetry.convo_session_drop(conversation_id, lane_key)


def build_history_prefix(conversation_id: str, recipient_lane: str,
                         max_chars: int, since_turn: int = 0) -> tuple[str, bool]:
    """Build the recipient-aware transcript to prepend before the next turn to `recipient_lane`.

    Dual-phase windowing (the technique zen uses): collect turns newest-first until the char
    budget is hit (so recent context is always kept), then present them chronologically (so the
    model reads a natural conversation). The recipient's own past turns are marked 'You', other
    lanes by name. The newest turn is always included even if it alone exceeds the budget.

    Returns (prefix, trimmed). When there's no prior history, returns ("", False) so the very
    first turn behaves exactly like a normal one-shot ask (zero regression).
    """
    turns = telemetry.convo_turns(conversation_id)
    if since_turn:                 # native resume: the lane's own session already holds the rest
        turns = [t for t in turns if int(t.get("turn_number", 0)) > since_turn]
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
