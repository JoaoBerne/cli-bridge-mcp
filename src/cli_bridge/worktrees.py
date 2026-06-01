"""Isolated write-mode: run a build-capable agent in a throwaway git worktree, return its diff.

Write mode (`agent: build`) lets a delegate edit files directly — convenient, but letting a
spawned model mutate your real working tree is risky. `ask_build_isolated` instead checks out a
detached git worktree at HEAD, points the agent there, captures the resulting `git diff`, and
discards the worktree. Your real repo is never touched; you review the diff and apply it
yourself. This is the RECOMMENDED way to use write mode.

v1 returns the diff only — there is no auto-apply (that would need explicit user approval).
git ops are real subprocess calls (git is already a dependency of the review workflow); the
agent run is injected via `run_lane` so the orchestration is testable without an AI CLI.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid

from .lanes import LaneSpec

_GIT_TIMEOUT_S = 30


def _git(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                           errors="replace", timeout=_GIT_TIMEOUT_S, check=False)
    except FileNotFoundError:
        return 127, "", "git is not installed / not on PATH."
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", f"git failed: {e}"
    return p.returncode, p.stdout, p.stderr


def _repo_root(cwd: str | None) -> tuple[str, str]:
    rc, out, err = _git(["rev-parse", "--show-toplevel"], cwd=cwd or ".")
    if rc != 0:
        return "", (err.strip() or "not a git repository")
    return out.strip(), ""


def _keep() -> bool:
    return os.environ.get("CLI_BRIDGE_KEEP_WORKTREES", "").strip().lower() in {"1", "true", "yes", "on"}


async def ask_build_isolated(lane: LaneSpec, args: dict, run_lane) -> str:
    """Run `lane` in build mode inside a temp worktree of the caller's repo; return its diff.
    The real repo is never modified."""
    if "agent" not in lane.caps:
        return f"[error] lane '{lane.key}' has no write/build mode — can't run an isolated build."
    task = (args.get("task") or "").strip()
    if not task:
        return "[error] task is required"

    cwd = (args.get("cwd") or "").strip()
    expanded = os.path.expanduser(cwd) if cwd else None
    root, err = _repo_root(expanded)
    if err:
        return (f"[error] {err}. ask_build_isolated needs a git repo (it works on a throwaway "
                "worktree). Run it inside your project, or pass cwd.")

    parent = tempfile.mkdtemp(prefix="cli-bridge-wt-")
    wt = os.path.join(parent, "tree")
    rc, _out, werr = _git(["-C", root, "worktree", "add", "--detach", wt, "HEAD"])
    if rc != 0:
        shutil.rmtree(parent, ignore_errors=True)
        return f"[error] could not create an isolated worktree: {werr.strip()}"

    try:
        sub = {"task": task, "agent": "build", "cwd": wt,
               "model": args.get("model"), "effort": args.get("effort"),
               "timeout_s": args.get("timeout_s")}
        res = await run_lane(lane, sub, tool="ask_build_isolated")
        # Stage everything (incl. new files) in the throwaway index, then diff vs HEAD.
        _git(["-C", wt, "add", "-A"])
        _drc, diff, _derr = _git(["-C", wt, "diff", "--cached"])
    finally:
        if _keep():
            kept = wt
        else:
            _git(["-C", root, "worktree", "remove", "--force", wt])
            shutil.rmtree(parent, ignore_errors=True)
            kept = None

    return _report(lane, res, diff, root, kept)


def _report(lane: LaneSpec, res, diff: str, root: str, kept: str | None) -> str:
    where = f"kept at `{kept}`" if kept else "discarded"
    lines = [f"# Isolated build (worktree)",
             f"_Agent: {lane.display} (build) · repo: `{root}` · worktree {where} · "
             "your repo was NOT modified_\n"]
    lines.append("## Agent output\n")
    lines.append(res.render().strip() or "_(no output)_")
    lines.append("\n## Proposed diff (review before applying — NOT applied)\n")
    if diff.strip():
        lines.append("```diff\n" + diff.rstrip() + "\n```")
    else:
        lines.append("_The agent made no file changes._")
    return "\n".join(lines)
