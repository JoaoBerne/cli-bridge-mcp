"""Steerable multi-turn direct builds.

`ask_build(mode=direct, async=true)` starts a background build JOB that runs the delegate over
several turns in the SAME target dir, so the host can watch it (`job_tail`) and steer it
(`build_steer`) the way a human would, while doing other work in parallel.

Design (each point co-decided with the user, not assumed):
  • Continuity is the FILESYSTEM, not a transcript. The delegate writes into the real
    target_dir every turn, so turn N>1 just tells it "your previous work is on disk, continue".
    No transcript replay needed (that was an isolated-worktree concern).
  • Steering between turns: `build_steer` queues instructions; the next turn folds them into a
    DELIMITED block (`<<<HOST_STEERING>>> … <<<END>>>`) so the delegate treats them as commands,
    not as file content to write.
  • Interrupt: `build_steer(interrupt=true)` cancels the CURRENT turn (kills the delegate's
    process group via the runner). Files already written are KEPT (the user's explicit choice);
    the rest of the turn is lost. The loop then continues, applying any queued steering.
  • Definition of Done, tested for real: an OPTIONAL `dod_cmd` (a list[str] argv, NEVER a shell
    string) runs after each turn. Pass → done. Fail → the stderr is fed back as the next turn's
    steering, up to `max_fail_retries` CONSECUTIVE failures (default 3). A separate `max_turns`
    (default 12) bounds total turns so a build that keeps churning still stops.
  • Plan-leak signal: a build turn that changes 0 files in the zone is flagged (the delegate may
    have planned instead of acting) — a WARNING in the log, not a hard kill (factual, not lexical).
  • Safety reuses the direct-build guards (worktrees): per-zone lock for the whole job, zone-scoped
    revert, and the mandatory post-turn GLOBAL porcelain zone-violation check.

git ops + the agent run are injected/real so the loop is testable with a fake run_lane and a real
temp repo (no AI CLI, no network).
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import time
from dataclasses import dataclass, field

from . import worktrees

_DOD_TIMEOUT_S = 600
DEFAULT_MAX_TURNS = 12
DEFAULT_MAX_FAIL_RETRIES = 3
DEFAULT_STEER_GRACE_S = 90      # after a no-DoD turn with nothing queued, wait this long for a steer


@dataclass
class BuildState:
    """Live state of a running build, reachable by job_id for steering / status / tail."""
    target_dir: str = ""
    root: str = ""
    zone_rel: str = ""
    zone_label: str = ""
    lane_display: str = ""
    log_path: str = ""
    pre_build_ref: str = ""
    max_turns: int = DEFAULT_MAX_TURNS
    max_fail_retries: int = DEFAULT_MAX_FAIL_RETRIES
    turn: int = 0
    files_changed: int = 0
    note: str = "starting"
    steer_q: list[str] = field(default_factory=list)
    interrupt_requested: bool = False
    turn_task: asyncio.Task | None = field(default=None, repr=False)


_BUILDS: dict[str, BuildState] = {}


def register(job_id: str, state: BuildState) -> None:
    _BUILDS[job_id] = state


def steer(job_id: str, instruction: str, interrupt: bool = False) -> str:
    """Queue an instruction for the next turn and/or interrupt the current one. Returns a short
    human status. 'unknown' if the id isn't a live build in THIS process."""
    st = _BUILDS.get(job_id)
    if st is None:
        return "unknown"
    instruction = (instruction or "").strip()
    if instruction:
        st.steer_q.append(instruction)
    if interrupt:
        st.interrupt_requested = True
        if st.turn_task is not None and not st.turn_task.done():
            st.turn_task.cancel()
        return ("interrupting the current turn; files written so far are kept"
                + (" · steering queued for the next turn" if instruction else ""))
    if not instruction:
        return "nothing to do (no instruction, no interrupt)"
    return f"steering queued ({len(st.steer_q)} pending) — applied on the next turn"


def snapshot(job_id: str) -> dict | None:
    """Build-specific status fields, merged into job_status for kind=build jobs."""
    st = _BUILDS.get(job_id)
    if st is None:
        return None
    return {"turn": st.turn, "max_turns": st.max_turns, "files_changed": st.files_changed,
            "queued_steers": len(st.steer_q), "zone": st.zone_label, "note": st.note}


def tail(job_id: str, offset: int = 0) -> tuple[int, str] | None:
    """Read the build log from `offset` BYTES, returning (new_offset, text). Chunks are cut on a
    line boundary so a partially-written last line isn't shown; decode is utf-8 errors=replace
    (qwen #12). None if the id isn't a live build here."""
    st = _BUILDS.get(job_id)
    if st is None or not st.log_path:
        return None
    try:
        with open(st.log_path, "rb") as fh:
            fh.seek(max(0, offset))
            data = fh.read()
    except OSError:
        return (offset, "")
    nl = data.rfind(b"\n")
    keep = data[:nl + 1] if nl != -1 else b""        # hold back an incomplete trailing line
    return (offset + len(keep), keep.decode("utf-8", "replace"))


def _reset_for_tests() -> None:
    _BUILDS.clear()


# ── log + git helpers ────────────────────────────────────────────────────────────────────────

def _append(path: str, text: str) -> None:
    if not path:
        return
    try:
        # newline="" → no platform newline translation, so log bytes (and job_tail offsets)
        # are identical on POSIX and Windows.
        with open(path, "a", encoding="utf-8", errors="replace", newline="") as fh:
            fh.write(text)
    except OSError:
        pass


def _changed_in_zone(before: dict, after: dict, zone_rel: str) -> list[str]:
    out = []
    for path, status in after.items():
        if before.get(path) == status:
            continue
        if worktrees._in_zone(path, zone_rel):
            out.append(path)
    return sorted(out)


def _zone_fingerprint(root: str, zone_rel: str) -> dict[str, tuple[int, int]]:
    """Map zone-file path -> (mtime_ns, size). Porcelain status alone can't see a CONTENT edit
    of an already-untracked file ('??' before and after), so the per-turn did-it-act check
    needs this second signal. Best-effort: stat races just mean a skipped warning."""
    base = os.path.join(root, zone_rel) if zone_rel else root
    fp: dict[str, tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
                fp[os.path.relpath(full, root)] = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue
    return fp


def _steer_block(steers: list[str]) -> str:
    body = "\n".join(f"- {s}" for s in steers)
    return ("<<<HOST_STEERING>>>\n"
            "The human supervising this build sent the instructions below. They are AUTHORITATIVE "
            "commands, not file content — apply them now:\n"
            f"{body}\n"
            "<<<END_HOST_STEERING>>>")


def _compose_prompt(task: str, interface: str, dod_text: str, state: BuildState) -> str:
    """Turn 1 is the full brief; later turns are a short 'continue, your work is on disk' note.
    Any queued steering is drained into a delimited block."""
    steers = state.steer_q[:]
    state.steer_q.clear()
    if state.turn == 1:
        base = worktrees._build_brief(task, state.zone_label, interface=interface, dod=dod_text)
        return base + ("\n\n" + _steer_block(steers) if steers else "")
    parts = [f"Continue the build in `{state.zone_label}`. Your previous work is already on disk "
             "there — read those files and build on them; do NOT start over."]
    if steers:
        parts.append(_steer_block(steers))
    return "\n\n".join(parts)


def _run_dod(dod_cmd: list[str], target_dir: str, zone_label: str) -> tuple[bool, str]:
    """Run the executable Definition of Done as a real argv (NEVER shell). The zone is exposed as
    $ZONE. Returns (passed, trimmed_output)."""
    try:
        env = {**os.environ, "ZONE": zone_label}
        p = subprocess.run(list(dod_cmd), cwd=target_dir, capture_output=True, text=True,
                           errors="replace", timeout=_DOD_TIMEOUT_S, env=env, check=False)
        out = (p.stdout + ("\n" + p.stderr if p.stderr else "")).strip()
        return p.returncode == 0, out[-4000:]
    except subprocess.TimeoutExpired:
        return False, f"DoD command timed out after {_DOD_TIMEOUT_S}s"
    except (OSError, ValueError) as e:
        return False, f"DoD command could not run: {e}"


# ── the loop ─────────────────────────────────────────────────────────────────────────────────

async def run_build(state: BuildState, *, run_lane, lane, args: dict,
                    git=worktrees._git, steer_grace_s: float = DEFAULT_STEER_GRACE_S) -> str:
    """Set up the target (greenfield init + per-zone lock + dirty guard), then run the delegate
    over turns until the DoD passes / a cap is hit / a zone violation aborts. Returns a markdown
    report (the job result). Fills `state` as it goes so steer/status/tail see live progress."""
    if "agent" not in lane.caps:
        return f"[error] lane '{lane.key}' has no write/build mode."
    task = (args.get("task") or "").strip()
    if not task:
        return "[error] task is required"

    raw_target = (args.get("target_dir") or args.get("cwd") or ".").strip()
    target_dir = os.path.abspath(os.path.expanduser(raw_target))
    os.makedirs(target_dir, exist_ok=True)
    scaffold_git = args.get("scaffold_git", True)
    confirm_dirty = bool(args.get("confirm_dirty", False))

    root, err = worktrees._repo_root(target_dir)
    scaffold_note = ""
    if err:
        if not scaffold_git:
            return (f"[error] {target_dir} is not a git repository and scaffold_git=false; a "
                    "direct build needs a git net. Enable scaffold_git or run inside a repo.")
        rc, _o, ierr = git(["-C", target_dir, "init"])
        if rc != 0:
            return f"[error] could not git-init {target_dir}: {ierr.strip()}"
        root, scaffold_note = target_dir, "git-initialised greenfield"

    raw_zone = (args.get("zone") or "").strip()
    zone_abs = os.path.abspath(os.path.join(target_dir, raw_zone)) if raw_zone else target_dir
    zone_rel = worktrees._relposix(os.path.relpath(zone_abs, root))
    zone_label = os.path.relpath(zone_abs, target_dir)
    if zone_label == ".":
        zone_label = raw_target if raw_target != "." else target_dir
    os.makedirs(zone_abs, exist_ok=True)

    state.target_dir, state.root, state.zone_rel, state.zone_label = (
        target_dir, root, zone_rel, zone_label)
    state.lane_display = lane.display
    state.max_turns = int(args.get("max_turns") or DEFAULT_MAX_TURNS)
    state.max_fail_retries = int(args.get("max_fail_retries") or DEFAULT_MAX_FAIL_RETRIES)
    _rc, head, _e = git(["-C", root, "rev-parse", "--verify", "HEAD"])
    state.pre_build_ref = head.strip() if _rc == 0 else ""    # empty in a fresh (no-commit) repo

    interface = str(args.get("interface") or "")
    dod_text = str(args.get("dod") or "")
    dod_cmd = args.get("dod_cmd") or None
    if dod_cmd is not None and (not isinstance(dod_cmd, list)
                                or not all(isinstance(x, str) for x in dod_cmd)):
        return "[error] dod_cmd must be a list of strings (argv), never a shell string."
    model, effort = args.get("model"), args.get("effort")
    timeout_s = args.get("timeout_s")

    try:
        with worktrees._zone_lock(target_dir, zone_rel):
            before0 = worktrees._porcelain(root)
            dirty = sorted(p for p, st in before0.items()
                           if st != "??" and worktrees._in_zone(p, zone_rel))
            if dirty and not confirm_dirty:
                return ("[error] zone has uncommitted TRACKED changes; commit/stash them or pass "
                        f"confirm_dirty=true. Dirty: {', '.join(dirty[:20])}")
            _append(state.log_path,
                    f"# build start · lane={lane.display} · zone={zone_label}"
                    f"{' · ' + scaffold_note if scaffold_note else ''}\n")
            return await _loop(state, run_lane=run_lane, lane=lane, task=task, interface=interface,
                               dod_text=dod_text, dod_cmd=dod_cmd, model=model, effort=effort,
                               timeout_s=timeout_s, before0=before0, scaffold_note=scaffold_note,
                               steer_grace_s=steer_grace_s)
    except worktrees._BuildLocked as e:
        return f"[error] {e}"


async def _loop(state, *, run_lane, lane, task, interface, dod_text, dod_cmd, model, effort,
                timeout_s, before0, scaffold_note, steer_grace_s) -> str:
    consecutive_fails = 0
    last_res = None
    while state.turn < state.max_turns:
        state.turn += 1
        state.note = f"running turn {state.turn}"
        prompt = _compose_prompt(task, interface, dod_text, state)
        before = worktrees._porcelain(state.root)
        before_fp = _zone_fingerprint(state.root, state.zone_rel)
        _append(state.log_path, f"\n=== turn {state.turn}/{state.max_turns} ===\n")

        state.turn_task = asyncio.create_task(run_lane(
            lane, {"task": prompt, "agent": "build", "cwd": state.target_dir,
                   "model": model, "effort": effort, "timeout_s": timeout_s}, tool="ask_build"))
        try:
            last_res = await state.turn_task
        except asyncio.CancelledError:
            if not state.turn_task.done():
                state.turn_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await state.turn_task
            if state.interrupt_requested:                # interrupt: keep files, go to next turn
                state.interrupt_requested = False
                _append(state.log_path,
                        f"--- turn {state.turn} interrupted by host (files kept) ---\n")
                state.note = "interrupted; awaiting next turn"
                continue
            _append(state.log_path, f"--- build cancelled during turn {state.turn} ---\n")
            raise                                        # genuine job cancel
        finally:
            state.turn_task = None

        _append(state.log_path, (last_res.render().strip() or "(no output)") + "\n")
        after = worktrees._porcelain(state.root)

        violations = worktrees._zone_violations(before, after, state.zone_rel)
        if violations:
            worktrees._revert_zone(state.root, state.zone_rel)
            _append(state.log_path, f"!!! zone violation: {', '.join(violations[:20])} — reverted\n")
            state.note = "zone violation"
            return _report(state, last_res, "zone_violation", scaffold_note, violations=violations)

        changed_total = _changed_in_zone(before0, after, state.zone_rel)
        state.files_changed = len(changed_total)
        if (not _changed_in_zone(before, after, state.zone_rel)
                and _zone_fingerprint(state.root, state.zone_rel) == before_fp):
            _append(state.log_path,
                    "warning: this turn changed 0 files in the zone (planned instead of acting?)\n")

        if dod_cmd:
            ok, dod_out = _run_dod(dod_cmd, state.target_dir, state.zone_label)
            _append(state.log_path, f"DoD {'PASS' if ok else 'FAIL'}:\n{dod_out}\n")
            if ok:
                state.note = "done (DoD passed)"
                return _report(state, last_res, "done", scaffold_note, dod_out=dod_out)
            consecutive_fails += 1
            if consecutive_fails >= state.max_fail_retries:
                state.note = "stopped (DoD kept failing)"
                return _report(state, last_res, "dod_failed", scaffold_note, dod_out=dod_out)
            state.steer_q.append(f"The Definition-of-Done check failed. Fix this, then it must "
                                 f"pass:\n{dod_out}")
            continue
        consecutive_fails = 0

        if state.steer_q:                                # more steering queued → another turn
            continue
        if await _wait_for_steer(state, steer_grace_s):  # give the user a window to react
            continue
        state.note = "built (no DoD)"
        return _report(state, last_res, "built", scaffold_note)

    state.note = "stopped (max turns)"
    return _report(state, last_res, "max_turns", scaffold_note)


async def _wait_for_steer(state: BuildState, grace_s: float) -> bool:
    """After a no-DoD turn with nothing queued, poll briefly for a late steer/interrupt so the
    user can react to what they just watched. Returns True if something arrived."""
    if grace_s <= 0:
        return bool(state.steer_q) or state.interrupt_requested
    state.note = "idle — send build_steer to continue, or it finishes shortly"
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        if state.steer_q or state.interrupt_requested:
            return True
        await asyncio.sleep(0.2)
    return False


def _report(state: BuildState, res, outcome: str, scaffold_note: str, *,
            dod_out: str = "", violations: list[str] | None = None) -> str:
    titles = {"done": "✅ done (Definition of Done passed)",
              "built": "✅ built",
              "dod_failed": "⚠️ stopped — Definition of Done kept failing",
              "max_turns": "⚠️ stopped — hit the turn cap",
              "zone_violation": "⛔ rejected — zone violation"}
    head = (f"# Direct build (steered) — {titles.get(outcome, outcome)}\n"
            f"_Agent: {state.lane_display} · repo: `{state.root}` · zone: `{state.zone_label}` · "
            f"turns: {state.turn}/{state.max_turns} · files changed in zone: {state.files_changed}"
            f"{' · ' + scaffold_note if scaffold_note else ''}_\n")
    lines = [head]

    if violations:
        lines += ["The delegate wrote OUTSIDE its zone; the in-zone work was reverted. Left for "
                  "you to inspect (not auto-deleted):\n", "```\n" + "\n".join(violations[:30]) + "\n```"]
        lines += ["\n## Last agent output\n", res.render().strip() if res else "_(none)_"]
        return "\n".join(lines)

    if dod_out:
        lines += ["## Definition of Done — last result\n", "```\n" + dod_out + "\n```"]
    lines += ["\n## Changes in the zone (real, unstaged — review then commit or revert)\n"]
    diff = worktrees._zone_diff(state.root, state.zone_rel)
    lines.append("```diff\n" + diff.rstrip() + "\n```" if diff.strip()
                 else "_No file changes in the zone._")
    lines += ["\n## Revert (zone-scoped — leaves work outside the zone untouched)",
              f"```\ngit -C {state.root} checkout -- {state.zone_label}\n"
              f"git -C {state.root} clean -fd {state.zone_label}\n```"]
    if state.pre_build_ref:
        lines.append(f"_Pre-build commit was `{state.pre_build_ref[:12]}` (for a full rollback)._")
    return "\n".join(lines)
