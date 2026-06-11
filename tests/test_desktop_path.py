"""GUI-host PATH fallback: which_path finds CLIs in common install dirs when the host
(Claude Desktop, Hermes Desktop, …) launched us with a minimal PATH."""

import os
import stat
import sys

import pytest

from cli_bridge import detect, lanes
from cli_bridge.lanes import LaneSpec, which_path


@pytest.fixture
def fake_bin_dir(tmp_path, monkeypatch):
    d = tmp_path / "bins"
    d.mkdir()
    exe = d / ("fakecli.exe" if sys.platform == "win32" else "fakecli")
    exe.write_text("#!/bin/sh\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setattr(lanes, "_EXTRA_BIN_DIRS", (str(d),))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))   # minimal GUI-style PATH
    return d


def test_which_path_falls_back_to_install_dirs(fake_bin_dir):
    found = which_path("fakecli")
    assert found is not None and found.startswith(str(fake_bin_dir))


def test_which_path_keeps_bare_name_when_on_path(monkeypatch):
    # Something guaranteed on PATH in tests: the python executable's dir.
    exe_dir, exe_name = os.path.split(sys.executable)
    monkeypatch.setenv("PATH", exe_dir)
    assert which_path(exe_name) == exe_name


def test_which_path_misses_cleanly(fake_bin_dir):
    assert which_path("definitely-not-a-cli") is None


def test_which_path_never_remaps_explicit_paths(fake_bin_dir):
    assert which_path("/nonexistent/dir/fakecli") is None


def test_lane_bin_and_detection_use_the_fallback(fake_bin_dir):
    lane = LaneSpec("fk", "Fake", "fakecli", lambda *a: [])
    assert detect.is_installed(lane)
    assert lane.bin.startswith(str(fake_bin_dir))   # absolute → spawnable without PATH
