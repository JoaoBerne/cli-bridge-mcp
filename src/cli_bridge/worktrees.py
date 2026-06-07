"""Write-mode delegation — two flavours, both with a git safety net.

`ask_build_isolated` (the default, RECOMMENDED): checks out a detached git worktree at HEAD,
points the agent there, captures the resulting `git diff`, and discards the worktree. Your real
repo is never touched; you review the diff and apply it yourself.

`ask_build_direct`: commissions a delegate to build a REAL, complete result straight into a
target directory — the host can do other work (e.g. the backend) in the SAME repo in parallel.
Safety is by git + a zone contract, not by isolation:
  • the delegate is told to write ONLY inside `zone` (a path under target_dir);
  • ALL git undo ops are scoped to that zone (`git checkout -- <zone>` + `git clean -fd <zone>`,
    NEVER a global `git reset --hard`), so the host's uncommitted work outside the zone is safe;
  • a per-zone atomic lock prevents two builds racing the same zone;
  • after the build, a GLOBAL `git status --porcelain` diff vs a pre-build snapshot catches any
    file the delegate wrote OUTSIDE its zone (escaping via `../`, an absolute path, a symlink) —
    git scoping protects git OPS, it cannot sandbox the subprocess, so this check is mandatory.
Greenfield (empty/new dir): created and `git init`-ed when scaffold_git, so the net always
exists. Direct builds need a git net; a non-repo target with scaffold_git=false is refused.

v1 returns the diff only — there is no auto-apply. git ops are real subprocess calls; the agent
run is injected via `run_lane` so the orchestration is testable without an AI CLI.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import subprocess
import tempfile
import time

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


def _architect_prompt(task: str) -> str:
    return (
        "You are the ARCHITECT. Write a precise, step-by-step implementation PLAN for the task "
        "below: which files to touch and exactly what edits to make (signatures, key lines, "
        "edge cases). Do NOT write the full code — another agent will implement your plan. Read "
        "the repo as needed; be concrete and minimal.\n\nTASK:\n" + task)


def _build_with_plan(task: str, plan: str) -> str:
    return (
        "Implement EXACTLY the plan below. Make the described file edits; do not redesign or "
        "expand the scope. If a step is impossible, do the rest and note why.\n\n"
        f"TASK:\n{task}\n\nPLAN (from the architect):\n{plan}")


async def ask_build_isolated(lane: LaneSpec, args: dict, run_lane,
                             architect: LaneSpec | None = None) -> str:
    """Run `lane` (the editor) in build mode inside a temp worktree of the caller's repo; return
    its diff. The real repo is never modified. With `architect`, that lane first writes a PLAN
    (read-only) which the editor implements — strong model plans, cheaper model applies."""
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

    plan = ""
    plan_note = ""
    try:
        # Architect step (optional, read-only): a plan the editor will implement.
        build_task = task
        if architect is not None:
            pr = await run_lane(architect, {"task": _architect_prompt(task), "cwd": wt,
                                            "timeout_s": args.get("timeout_s")},
                                tool="ask_build_isolated")
            if pr.ok and pr.output.strip():
                plan = pr.output.strip()
                build_task = _build_with_plan(task, plan)
                plan_note = f" · architect: {architect.display}"
            else:
                plan_note = f" · architect {architect.display} FAILED ({pr.kind}) — editor built solo"
        sub = {"task": build_task, "agent": "build", "cwd": wt,
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

    return _report(lane, res, diff, root, kept, plan=plan, plan_note=plan_note)


def _report(lane: LaneSpec, res, diff: str, root: str, kept: str | None,
            *, plan: str = "", plan_note: str = "") -> str:
    where = f"kept at `{kept}`" if kept else "discarded"
    lines = ["# Isolated build (worktree)",
             f"_Agent: {lane.display} (build){plan_note} · repo: `{root}` · worktree {where} · "
             "your repo was NOT modified_\n"]
    if plan:
        lines.append("## Plan (architect)\n")
        lines.append(plan.strip())
        lines.append("")
    lines.append("## Agent output\n")
    lines.append(res.render().strip() or "_(no output)_")
    lines.append("\n## Proposed diff (review before applying — NOT applied)\n")
    if diff.strip():
        lines.append("```diff\n" + diff.rstrip() + "\n```")
    else:
        lines.append("_The agent made no file changes._")
    return "\n".join(lines)


# ───────────────────────────────── direct build (real, in-repo) ─────────────────────────────

def _build_brief(task: str, zone_label: str, *, interface: str = "", dod: str = "") -> str:
    """Compose the delegate's prompt as a real spec: objective, the ONE zone it may write, an
    optional interface contract (so the host can wire its own work to the result) and an optional
    textual Definition of Done. Pure + testable (an executable DoD is Phase 3)."""
    parts = [
        "You are a BUILD agent working DIRECTLY in a real repository. Follow this brief exactly.",
        "",
        "## Objective",
        task.strip(),
        "",
        "## Zone — the ONLY place you may write",
        f"Create and edit files ONLY inside: `{zone_label}`.",
        "Do NOT touch, move, or delete anything outside this path: no parent directories, no "
        "absolute paths outside the zone, no symlinks that escape it. Anything you write outside "
        "the zone will be detected and the whole build rejected and reverted.",
    ]
    if interface.strip():
        parts += ["", "## Interface contract (match this so other work can wire onto yours)",
                  interface.strip()]
    if dod.strip():
        parts += ["", "## Definition of Done", dod.strip()]
    parts += ["", "Make the minimal, complete set of changes that satisfies the objective, then "
              "stop. Do not add features that were not requested."]
    return "\n".join(parts)


class _BuildLocked(Exception):
    """Raised when another build already holds this zone's lock."""


def _lock_path(target_dir: str, zone_rel: str) -> str:
    h = hashlib.sha256(f"{os.path.abspath(target_dir)}\x00{zone_rel}".encode()).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), f"cli-bridge-build-{h}.lock")


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        return True            # staleness reclaim is POSIX-only; never reclaim on Windows
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True            # exists but not ours, or unknown — treat as live (conservative)
    return True


def _read_lock_pid(path: str) -> int | None:
    try:
        with open(path) as fh:
            return int(fh.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _acquire(path: str) -> int | None:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None
    os.write(fd, f"{os.getpid()} {int(time.time())}".encode())
    return fd


@contextlib.contextmanager
def _zone_lock(target_dir: str, zone_rel: str):
    """Atomic per-ZONE lock (O_CREAT|O_EXCL, cross-platform). Two builds on DISJOINT zones of the
    same repo run fine; two on the SAME zone — the second is refused. A lock left by a dead pid is
    reclaimed once. The pid+timestamp is for staleness only, not ownership."""
    path = _lock_path(target_dir, zone_rel)
    fd = _acquire(path)
    if fd is None:                                   # held — is the holder still alive?
        old = _read_lock_pid(path)
        if old is None or not _pid_alive(old):       # stale → reclaim once
            with contextlib.suppress(OSError):
                os.unlink(path)
            fd = _acquire(path)
    if fd is None:
        raise _BuildLocked(
            f"another build is already running on zone '{zone_rel}' of {target_dir} "
            f"(lock {path}); wait for it, or delete the lock file if it is stale.")
    try:
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(path)


def _relposix(p: str) -> str:
    return p.replace(os.sep, "/")


def _in_zone(path_rel: str, zone_rel: str) -> bool:
    """Is a repo-root-relative path inside the zone? zone_rel '' or '.' means the whole repo."""
    if zone_rel in ("", "."):
        return True
    path_rel = _relposix(path_rel).strip("/")
    zone_rel = _relposix(zone_rel).strip("/")
    return path_rel == zone_rel or path_rel.startswith(zone_rel + "/")


def _porcelain(root: str) -> dict[str, str]:
    """Map repo-root-relative path -> two-char status, from `git status --porcelain` (whole repo).
    `-uall` expands untracked DIRECTORIES into individual files — without it git collapses e.g.
    `backend/` to one entry, which would hide a file the delegate slipped into a pre-existing
    out-of-zone dir (the exact escape the zone check must catch). Ignored files stay excluded."""
    _rc, out, _err = _git(["-C", root, "status", "--porcelain", "--untracked-files=all"])
    paths: dict[str, str] = {}
    for line in out.splitlines():
        if len(line) < 4:
            continue
        status, rest = line[:2], line[3:]
        if " -> " in rest:                           # rename/copy: the destination is what exists
            rest = rest.split(" -> ", 1)[1]
        paths[rest.strip().strip('"')] = status
    return paths


def _zone_violations(before: dict[str, str], after: dict[str, str], zone_rel: str) -> list[str]:
    """Paths that CHANGED (or appeared) during the build AND sit OUTSIDE the zone. Comparing
    against the pre-build snapshot means the host's own pre-existing out-of-zone work is NOT
    flagged — only what the delegate touched outside its lane is."""
    out = []
    for path, status in after.items():
        if before.get(path) == status:               # unchanged since before the build
            continue
        if not _in_zone(path, zone_rel):
            out.append(path)
    return sorted(out)


async def ask_build_direct(lane: LaneSpec, args: dict, run_lane,
                           build_disabled: bool = False) -> str:
    """Commission `lane` to build DIRECTLY into a real target dir, guarded by git + a zone
    contract. Returns a report with the agent output, the zone diff, and revert instructions.
    The host's uncommitted work outside the zone is never touched."""
    if build_disabled:
        return ("[error] direct builds are disabled on this machine (CLI_BRIDGE_NO_BUILD). "
                "Use ask_build mode=isolated for a review-only diff.")
    if "agent" not in lane.caps:
        return f"[error] lane '{lane.key}' has no write/build mode — can't run a direct build."
    task = (args.get("task") or "").strip()
    if not task:
        return "[error] task is required"

    raw_target = (args.get("target_dir") or args.get("cwd") or ".").strip()
    target_dir = os.path.abspath(os.path.expanduser(raw_target))
    os.makedirs(target_dir, exist_ok=True)           # greenfield: create the dir if absent

    scaffold_git = args.get("scaffold_git", True)
    confirm_dirty = bool(args.get("confirm_dirty", False))

    root, err = _repo_root(target_dir)
    scaffold_note = ""
    if err:                                           # target is not inside any git repo
        if not scaffold_git:
            return (f"[error] {target_dir} is not a git repository and scaffold_git=false. A "
                    "direct build needs a git net (diff / revert / zone-guard). Enable "
                    "scaffold_git, or run inside an existing repo.")
        rc, _out, ierr = _git(["-C", target_dir, "init"])
        if rc != 0:
            return f"[error] could not git-init {target_dir}: {ierr.strip()}"
        root, scaffold_note = target_dir, "git-initialised greenfield"

    # Zone: a path under target_dir the delegate may write to (default = the whole target dir),
    # expressed relative to the repo ROOT for porcelain comparisons.
    raw_zone = (args.get("zone") or "").strip()
    zone_abs = os.path.abspath(os.path.join(target_dir, raw_zone)) if raw_zone else target_dir
    zone_rel = _relposix(os.path.relpath(zone_abs, root))
    zone_label = os.path.relpath(zone_abs, target_dir)
    if zone_label == ".":
        zone_label = raw_target if raw_target != "." else target_dir
    os.makedirs(zone_abs, exist_ok=True)

    try:
        with _zone_lock(target_dir, zone_rel):
            before = _porcelain(root)
            dirty = sorted(p for p, st in before.items()
                           if st != "??" and _in_zone(p, zone_rel))
            if dirty and not confirm_dirty:
                listing = "\n".join(f"  {p}" for p in dirty[:20])
                return (f"[error] zone '{zone_label}' has uncommitted TRACKED changes — a direct "
                        "build could clobber them. Commit/stash them, or pass confirm_dirty=true "
                        f"to build anyway.\nDirty in zone:\n{listing}")

            brief = _build_brief(task, zone_label,
                                 interface=str(args.get("interface") or ""),
                                 dod=str(args.get("dod") or ""))
            sub = {"task": brief, "agent": "build", "cwd": target_dir,
                   "model": args.get("model"), "effort": args.get("effort"),
                   "timeout_s": args.get("timeout_s")}
            res = await run_lane(lane, sub, tool="ask_build")

            after = _porcelain(root)
            violations = _zone_violations(before, after, zone_rel)
            if violations:
                # Reject: undo the in-zone work (scoped), leave any escaped files for the user to
                # inspect (auto-deleting them could destroy host work we can't attribute).
                _git(["-C", root, "checkout", "--", zone_rel or "."])
                _git(["-C", root, "clean", "-fd", "--", zone_rel or "."])
                return _report_violation(lane, res, root, zone_label, violations)

            # Show new + modified in the zone without permanently staging: intent-to-add untracked,
            # diff, then unstage so the host's index is left as it was.
            _git(["-C", root, "add", "-N", "--", zone_rel or "."])
            _drc, diff, _derr = _git(["-C", root, "diff", "--", zone_rel or "."])
            _git(["-C", root, "reset", "-q", "--", zone_rel or "."])
    except _BuildLocked as e:
        return f"[error] {e}"

    return _report_direct(lane, res, diff, root, zone_label, scaffold_note)


def _report_direct(lane: LaneSpec, res, diff: str, root: str, zone_label: str,
                   scaffold_note: str) -> str:
    head = f"_Agent: {lane.display} (build) · repo: `{root}` · zone: `{zone_label}`"
    if scaffold_note:
        head += f" · {scaffold_note}"
    head += " · files written to your REAL repo (in the zone) — review below_\n"
    lines = ["# Direct build", head, "## Agent output\n",
             res.render().strip() or "_(no output)_",
             "\n## Changes in the zone (real, unstaged — review then commit or revert)\n"]
    if diff.strip():
        lines.append("```diff\n" + diff.rstrip() + "\n```")
    else:
        lines.append("_The agent made no file changes in the zone._")
    lines += ["\n## Revert (zone-scoped — leaves work outside the zone untouched)",
              f"```\ngit -C {root} checkout -- {zone_label}\ngit -C {root} clean -fd {zone_label}\n```"]
    return "\n".join(lines)


def _report_violation(lane: LaneSpec, res, root: str, zone_label: str,
                      violations: list[str]) -> str:
    listing = "\n".join(f"  {p}" for p in violations[:30])
    return "\n".join([
        "# Direct build — REJECTED (zone violation)",
        f"_Agent: {lane.display} (build) · repo: `{root}` · zone: `{zone_label}`_\n",
        "The delegate wrote OUTSIDE its zone. The in-zone changes were reverted. The files below "
        "were left in place for you to inspect (they may be legitimate host work or an escape — "
        "cli-bridge will not auto-delete what it cannot attribute):\n",
        f"```\n{listing}\n```",
        "\n## Agent output\n",
        res.render().strip() or "_(no output)_",
    ])
