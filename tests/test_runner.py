import os
import time

from cli_bridge import runner


def test_success_returns_stdout_only():
    r = runner.run(["sh", "-c", "echo HELLO; echo noise 1>&2"], 30)
    assert r.ok and r.output == "HELLO"          # stderr noise dropped on exit 0


def test_failure_keeps_stderr_and_classifies():
    r = runner.run(["sh", "-c", "echo boom 1>&2; exit 3"], 30)
    assert not r.ok and r.kind == "failed" and "boom" in r.output and "exit 3" in r.output


def test_quota_classified():
    r = runner.run(["sh", "-c", "echo RESOURCE_EXHAUSTED 1>&2; exit 1"], 30)
    assert r.kind == "quota"


def test_auth_classified():
    r = runner.run(["sh", "-c", "echo 'Error: not logged in' 1>&2; exit 1"], 30)
    assert r.kind == "auth"


def test_binary_missing():
    r = runner.run(["zzz-no-such-bin-xyz"], 5)
    assert not r.ok and r.kind == "not_found"


def test_empty_command():
    r = runner.run([], 5)
    assert not r.ok and r.kind == "spawn"


def test_timeout_kills_grandchild():
    marker = "/tmp/cli_bridge_orphan_marker"
    if os.path.exists(marker):
        os.remove(marker)
    # parent spawns a grandchild that writes the marker after 4s, then sleeps 30s
    r = runner.run(["sh", "-c", f"(sleep 4; touch {marker}) & sleep 30"], 2)
    assert not r.ok and r.kind == "timeout"
    time.sleep(6)
    assert not os.path.exists(marker), "grandchild survived the group kill"
    if os.path.exists(marker):
        os.remove(marker)


def test_output_capped():
    r = runner.run(["sh", "-c", "yes x | head -c 300000"], 30)
    assert "clipped at" in r.output and len(r.output) < runner.MAX_OUTPUT_CHARS + 500


def test_redaction():
    r = runner.run(["sh", "-c", "echo 'api_key=supersecretvalue123'"], 30)
    assert "supersecretvalue123" not in r.output and "[redacted]" in r.output


def test_render_error_prefix():
    r = runner.RunResult(False, "boom", "failed")
    assert r.render().startswith("[failed]")
