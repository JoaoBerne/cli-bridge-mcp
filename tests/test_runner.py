import os
import sys
import time

import pytest

from cli_bridge import runner

# These exercise the runner via a POSIX shell (`sh -c …`). The runner itself is portable (it has
# a Windows process-kill branch), but these specific tests need `sh`, so skip them on Windows.
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="uses POSIX shell (sh)")


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


def test_empty_exit0_is_soft_failure():
    # A CLI that exits clean but prints nothing (e.g. agy in print mode) must NOT count as a
    # successful answer — it's a soft failure so ask_cascade/ask_best fall through to a real one.
    r = runner.run(["sh", "-c", "exit 0"], 30)
    assert not r.ok and r.kind == "empty"


def test_exit0_stderr_only_still_answers():
    # A short answer on stderr with exit 0 is still a real answer (not empty).
    r = runner.run(["sh", "-c", "echo theanswer 1>&2"], 30)
    assert r.ok and r.output == "theanswer"


_AUP = ("API Error: Claude Code is unable to respond to this request, which appears to "
        "violate our Usage Policy (https://www.anthropic.com/legal/aup). "
        "Request ID: req_011Cbj4UZiWHzWuQ8M1Eo29i")


def test_policy_refusal_exit0_is_soft_failure():
    # Claude Code refuses on policy grounds and exits 0 — must NOT be returned as a successful
    # answer (it would be cached + shown as if the lane answered). Soft failure → fall through.
    r = runner.run(["sh", "-c", f"echo {repr(_AUP)}"], 30)
    assert not r.ok and r.kind == "policy"


def test_policy_refusal_nonzero_classified():
    r = runner.run(["sh", "-c", f"echo {repr(_AUP)} 1>&2; exit 1"], 30)
    assert r.kind == "policy"


def test_policy_fingerprint_does_not_misfire():
    # A normal answer that merely MENTIONS the words must stay a successful answer.
    text = "Our usage policy doc explains the API Error codes; here is the answer: 42."
    assert runner._is_policy_refusal(text) is False
    r = runner.run(["sh", "-c", f"echo {repr(text)}"], 30)
    assert r.ok and r.kind == "ok"


def test_policy_refusal_split_across_streams():
    # Refusal halves on different streams (exit 0): the combined-blob check must still catch it
    # (regression for the gap the council's review_diff flagged on this very fix).
    r = runner.run(["sh", "-c",
                    "echo 'unable to respond to this request'; "
                    "echo 'this appears to violate our Usage Policy' 1>&2"], 30)
    assert not r.ok and r.kind == "policy"


def test_failure_kind_unit():
    # Direct coverage of the shared classifier (council review asked for it).
    assert runner._failure_kind("", "RESOURCE_EXHAUSTED") == "quota"
    assert runner._failure_kind("", "not logged in") == "auth"
    assert runner._failure_kind("boom", "") == "failed"
    assert runner._failure_kind(_AUP, "") == "policy"
    # policy wins over a quota-looking word when the refusal envelope is present
    assert runner._failure_kind(_AUP, "rate limit") == "policy"


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
