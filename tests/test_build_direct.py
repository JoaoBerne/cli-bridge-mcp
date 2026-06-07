"""Direct build: a delegate writes REAL files into a target dir, guarded by git + a zone
contract. Uses a real temp git repo (git only — no AI CLI, no network). The agent run is a fake
`run_lane` that writes files into the build cwd, so we exercise the git/zone/lock machinery."""
import asyncio
import os
import subprocess
import sys

import pytest

from cli_bridge import worktrees
from cli_bridge.lanes import LaneSpec
from cli_bridge.runner import RunResult


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    _git(["init", "-q"], d)
    _git(["config", "user.email", "t@t.t"], d)
    _git(["config", "user.name", "t"], d)
    (d / "README.md").write_text("base\n")
    _git(["add", "-A"], d)
    _git(["commit", "-qm", "init"], d)
    return d


def _lane():
    return LaneSpec("opencode", "Opencode", "echo", lambda *a: [], caps=("model", "effort", "agent"))


def _writer(files: dict):
    """Fake build agent: writes each {rel_path: content} into the build cwd (target_dir). `bytes`
    content is written binary (for artifact tests); `str` content is written as text."""
    async def run_lane(lane, args, *, tool="ask", terse=True):
        assert args.get("agent") == "build"          # a direct build must request write mode
        for rel, content in files.items():
            p = os.path.join(args["cwd"], rel)
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            if isinstance(content, bytes):
                with open(p, "wb") as fh:
                    fh.write(content)
            else:
                with open(p, "w") as fh:
                    fh.write(content)
        return RunResult(True, f"wrote {', '.join(files)}", "ok", latency_ms=10)
    return run_lane


def _run(args, files, **kw):
    return asyncio.run(worktrees.ask_build_direct(_lane(), args, _writer(files), **kw))


# ── brief ───────────────────────────────────────────────────────────────────────────────────

def test_build_brief_contains_objective_zone_and_dod():
    b = worktrees._build_brief("make a login page", "frontend", dod="`npm run build` passes")
    assert "make a login page" in b and "frontend" in b
    assert "Objective" in b and "Definition of Done" in b and "npm run build" in b
    assert "ONLY" in b                               # the zone restriction is stated


# ── greenfield ──────────────────────────────────────────────────────────────────────────────

def test_direct_greenfield_creates_inits_and_writes(tmp_path):
    target = tmp_path / "site"                        # does not exist yet
    report = _run({"task": "make a page", "target_dir": str(target)},
                  {"index.html": "<h1>hi</h1>\n"})
    assert "# Direct build" in report
    assert (target / "index.html").read_text() == "<h1>hi</h1>\n"   # real file in real dir
    assert (target / ".git").exists()                # greenfield got a git net
    assert "git-initialised greenfield" in report
    assert "index.html" in report and "<h1>hi</h1>" in report       # diff is shown
    assert "checkout -- " in report and "reset --hard" not in report  # zone-scoped revert only


def test_direct_greenfield_untracked_is_not_dirty(tmp_path):
    # An empty greenfield dir is never "dirty" — untracked files don't block the build.
    target = tmp_path / "fresh"
    report = _run({"task": "t", "target_dir": str(target)}, {"a.txt": "x\n"})
    assert "# Direct build" in report and (target / "a.txt").exists()


# ── zone enforcement ────────────────────────────────────────────────────────────────────────

def test_direct_zone_violation_rejected_and_reverted(repo):
    # Host's own parallel work, OUTSIDE the zone, already on disk before the build starts.
    (repo / "backend").mkdir()
    (repo / "backend" / "server.py").write_text("# host backend\n")
    report = _run(
        {"task": "build front", "target_dir": str(repo), "zone": "frontend"},
        {"frontend/app.js": "console.log(1)\n", "backend/evil.py": "# escaped\n"})
    assert "REJECTED (zone violation)" in report
    assert "backend/evil.py" in report                       # the escape is reported
    assert not (repo / "frontend" / "app.js").exists()       # in-zone work reverted
    assert (repo / "backend" / "evil.py").exists()           # escape left for inspection
    assert (repo / "backend" / "server.py").read_text() == "# host backend\n"  # host untouched


def test_direct_in_zone_build_leaves_host_work_alone(repo):
    # Pre-existing host work outside the zone must NOT be flagged as a violation (it's in the
    # before-snapshot) and must survive an in-zone build.
    (repo / "backend").mkdir()
    (repo / "backend" / "server.py").write_text("# host\n")
    report = _run({"task": "t", "target_dir": str(repo), "zone": "frontend"},
                  {"frontend/app.js": "ok\n"})
    assert "# Direct build" in report and "REJECTED" not in report
    assert (repo / "frontend" / "app.js").exists()
    assert (repo / "backend" / "server.py").read_text() == "# host\n"


# ── dirty-zone guard ────────────────────────────────────────────────────────────────────────

def _commit_tracked_front(repo):
    (repo / "frontend").mkdir()
    (repo / "frontend" / "index.html").write_text("v1\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "front"], repo)
    (repo / "frontend" / "index.html").write_text("v2-uncommitted\n")   # tracked modification


def test_direct_dirty_zone_stops_without_confirm(repo):
    _commit_tracked_front(repo)
    report = _run({"task": "t", "target_dir": str(repo), "zone": "frontend"},
                  {"frontend/app.js": "x\n"})
    assert "uncommitted TRACKED changes" in report and "confirm_dirty" in report
    assert not (repo / "frontend" / "app.js").exists()       # build did not run


def test_direct_dirty_zone_with_confirm_builds(repo):
    _commit_tracked_front(repo)
    report = _run({"task": "t", "target_dir": str(repo), "zone": "frontend", "confirm_dirty": True},
                  {"frontend/app.js": "x\n"})
    assert "# Direct build" in report and (repo / "frontend" / "app.js").exists()


# ── build disabled (team lock) ──────────────────────────────────────────────────────────────

def test_direct_build_disabled_refuses(repo):
    report = _run({"task": "t", "target_dir": str(repo)}, {"a.txt": "x\n"}, build_disabled=True)
    assert "disabled" in report and not (repo / "a.txt").exists()


def test_direct_non_git_without_scaffold_refused(tmp_path):
    target = tmp_path / "plain"                       # not a repo, scaffold off → no safety net
    report = _run({"task": "t", "target_dir": str(target), "scaffold_git": False}, {"a.txt": "x\n"})
    assert "not a git repository" in report and "scaffold_git" in report
    assert not (target / "a.txt").exists()


# ── artifact return (G.1: non-text files surfaced by path, not diffed) ────────────────────────

def test_direct_build_reports_binary_file_as_artifact(repo):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64          # NUL bytes -> detected as binary
    report = _run({"task": "make a chart", "target_dir": str(repo), "zone": "assets"},
                  {"assets/chart.png": png, "assets/notes.txt": "see the chart\n"})
    assert "# Direct build" in report
    assert "## Artifacts" in report
    assert "chart.png" in report and "image/png" in report     # surfaced by path + type
    assert (repo / "assets" / "chart.png").exists()
    # the binary is NOT dumped as a diff (no "Binary files differ"); the text file still diffs
    assert "Binary files" not in report
    assert "notes.txt" in report and "see the chart" in report


def test_direct_build_text_only_has_no_artifacts_section(repo):
    report = _run({"task": "write code", "target_dir": str(repo), "zone": "src"},
                  {"src/app.py": "print('hi')\n"})
    assert "# Direct build" in report and "## Artifacts" not in report


# ── per-zone lock ───────────────────────────────────────────────────────────────────────────

def test_zone_lock_same_zone_refuses_second(tmp_path):
    td = str(tmp_path)
    with worktrees._zone_lock(td, "frontend"):
        with pytest.raises(worktrees._BuildLocked):
            with worktrees._zone_lock(td, "frontend"):
                pass


def test_zone_lock_disjoint_zones_both_held(tmp_path):
    td = str(tmp_path)
    with worktrees._zone_lock(td, "frontend"):
        with worktrees._zone_lock(td, "backend"):     # different zone → no contention
            pass


@pytest.mark.skipif(sys.platform == "win32",
                    reason="dead-pid lock reclaim is POSIX-only (Windows: lock is conservative, "
                           "the error message tells the user to delete a stale lock)")
def test_zone_lock_reclaims_dead_pid(tmp_path):
    td = str(tmp_path)
    path = worktrees._lock_path(td, "frontend")
    with open(path, "w") as fh:
        fh.write("999999999 123")                     # a pid that (almost certainly) does not exist
    with worktrees._zone_lock(td, "frontend"):        # stale lock → reclaimed
        pass
    assert not os.path.exists(path)                    # released on exit
