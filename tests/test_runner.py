import asyncio
import os
import sys
import time

import pytest

from cli_bridge import runner

# These exercise the runner via a POSIX shell (`sh -c …`). The runner itself is portable (it has
# a Windows process-kill branch), but these specific tests need `sh`, so skip them on Windows.
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="uses POSIX shell (sh)")


def _run(argv, timeout_s, cwd=None, env=None):
    """Sync wrapper so these tests exercise the ONE spawn path (arun) without going async."""
    return asyncio.run(runner.arun(argv, timeout_s, cwd=cwd, env=env))


def test_success_returns_stdout_only():
    r = _run(["sh", "-c", "echo HELLO; echo noise 1>&2"], 30)
    assert r.ok and r.output == "HELLO"          # stderr noise dropped on exit 0


def test_failure_keeps_stderr_and_classifies():
    r = _run(["sh", "-c", "echo boom 1>&2; exit 3"], 30)
    assert not r.ok and r.kind == "failed" and "boom" in r.output and "exit 3" in r.output


def test_quota_classified():
    r = _run(["sh", "-c", "echo RESOURCE_EXHAUSTED 1>&2; exit 1"], 30)
    assert r.kind == "quota"


def test_auth_classified():
    r = _run(["sh", "-c", "echo 'Error: not logged in' 1>&2; exit 1"], 30)
    assert r.kind == "auth"


def test_binary_missing():
    r = _run(["zzz-no-such-bin-xyz"], 5)
    assert not r.ok and r.kind == "not_found"


def test_empty_command():
    r = _run([], 5)
    assert not r.ok and r.kind == "spawn"


def test_empty_exit0_is_soft_failure():
    # A CLI that exits clean but prints nothing (e.g. agy in print mode) must NOT count as a
    # successful answer — it's a soft failure so ask_cascade/ask_best fall through to a real one.
    r = _run(["sh", "-c", "exit 0"], 30)
    assert not r.ok and r.kind == "empty"


def test_exit0_stderr_only_still_answers():
    # A short answer on stderr with exit 0 is still a real answer (not empty).
    r = _run(["sh", "-c", "echo theanswer 1>&2"], 30)
    assert r.ok and r.output == "theanswer"


_AUP = ("API Error: Claude Code is unable to respond to this request, which appears to "
        "violate our Usage Policy (https://www.anthropic.com/legal/aup). "
        "Request ID: req_011Cbj4UZiWHzWuQ8M1Eo29i")


def test_policy_refusal_exit0_is_soft_failure():
    # Claude Code refuses on policy grounds and exits 0 — must NOT be returned as a successful
    # answer (it would be cached + shown as if the lane answered). Soft failure → fall through.
    r = _run(["sh", "-c", f"echo {repr(_AUP)}"], 30)
    assert not r.ok and r.kind == "policy"


def test_policy_refusal_nonzero_classified():
    r = _run(["sh", "-c", f"echo {repr(_AUP)} 1>&2; exit 1"], 30)
    assert r.kind == "policy"


def test_policy_fingerprint_does_not_misfire():
    # A normal answer that merely MENTIONS the words must stay a successful answer.
    text = "Our usage policy doc explains the API Error codes; here is the answer: 42."
    assert runner._is_policy_refusal(text) is False
    r = _run(["sh", "-c", f"echo {repr(text)}"], 30)
    assert r.ok and r.kind == "ok"


def test_policy_refusal_split_across_streams():
    # Refusal halves on different streams (exit 0): the combined-blob check must still catch it
    # (regression for the gap the council's review_diff flagged on this very fix).
    r = _run(["sh", "-c",
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
    r = _run(["sh", "-c", f"(sleep 4; touch {marker}) & sleep 30"], 2)
    assert not r.ok and r.kind == "timeout"
    time.sleep(6)
    assert not os.path.exists(marker), "grandchild survived the group kill"
    if os.path.exists(marker):
        os.remove(marker)


def test_output_capped():
    r = _run(["sh", "-c", "yes x | head -c 300000"], 30)
    assert "clipped at" in r.output and len(r.output) < runner.MAX_OUTPUT_CHARS + 500


def test_redaction():
    r = _run(["sh", "-c", "echo 'api_key=supersecretvalue123'"], 30)
    assert "supersecretvalue123" not in r.output and "[redacted]" in r.output


def test_render_error_prefix():
    r = runner.RunResult(False, "boom", "failed")
    assert r.render().startswith("[failed]")


# ── streaming path (Phase 1) ────────────────────────────────────────────────────────────────
# Passing on_line/log_path switches arun to _arun_streamed: two concurrent readers + proc.wait
# under the outer timeout, plus a no-output stall guard. The final result must classify exactly
# like the buffered path (same _finish), so these mirror the buffered tests where it matters.


def _run_stream(argv, timeout_s, on_line=None, log_path=None, no_output_timeout=120):
    async def go():
        return await runner.arun(argv, timeout_s, on_line=on_line, log_path=log_path,
                                 no_output_timeout=no_output_timeout)
    return asyncio.run(go())


def test_streaming_lines_arrive_in_order():
    seen = []
    r = _run_stream(["sh", "-c", "echo one; echo two; echo three"], 30,
                    on_line=lambda stream, text: seen.append((stream, text.rstrip("\n"))))
    assert r.ok and r.output == "one\ntwo\nthree"          # final output == buffered output
    assert [t for _, t in seen] == ["one", "two", "three"]  # delivered incrementally, in order
    assert all(s == "stdout" for s, _ in seen)


def test_streaming_classifies_like_buffered():
    # quota / empty / policy must classify the same whether streamed or buffered.
    assert _run_stream(["sh", "-c", "echo RESOURCE_EXHAUSTED 1>&2; exit 1"], 30,
                       on_line=lambda *a: None).kind == "quota"
    r_empty = _run_stream(["sh", "-c", "exit 0"], 30, on_line=lambda *a: None)
    assert not r_empty.ok and r_empty.kind == "empty"
    r_pol = _run_stream(["sh", "-c", f"echo {repr(_AUP)}"], 30, on_line=lambda *a: None)
    assert not r_pol.ok and r_pol.kind == "policy"


def test_streaming_log_path_captures_both_streams(tmp_path):
    p = tmp_path / "run.log"
    r = _run_stream(["sh", "-c", "echo a; echo b 1>&2; echo c"], 30, log_path=str(p))
    assert r.ok and r.output == "a\nc"                    # exit 0 → stdout only in the result
    content = p.read_text()
    assert "a\n" in content and "b\n" in content and "c\n" in content  # log sink keeps stderr too


def test_streaming_redacts_before_log_and_callback(tmp_path):
    p = tmp_path / "r.log"
    seen = []
    r = _run_stream(["sh", "-c", "echo 'api_key=supersecretvalue123'"], 30, log_path=str(p),
                    on_line=lambda s, t: seen.append(t))
    assert "supersecretvalue123" not in r.output and "[redacted]" in r.output
    assert "supersecretvalue123" not in p.read_text()      # secret never reaches the log file
    assert all("supersecretvalue123" not in t for t in seen)  # nor the live callback


def test_streaming_stderr_burst_does_not_deadlock():
    # 64 KB onto stderr while stdout stays idle until the very end. With a single buffered pipe
    # this is the classic deadlock; two concurrent readers must drain it (qwen #4).
    r = _run_stream(["sh", "-c", "yes E | head -c 65536 1>&2; echo DONE"], 30,
                    on_line=lambda *a: None)
    assert r.ok and r.output == "DONE"


def test_streaming_timeout_kills_group():
    marker = "/tmp/cli_bridge_stream_marker"
    if os.path.exists(marker):
        os.remove(marker)
    r = _run_stream(["sh", "-c", f"(sleep 4; touch {marker}) & sleep 30"], 2,
                    on_line=lambda *a: None)
    assert not r.ok and r.kind == "timeout"
    time.sleep(6)
    assert not os.path.exists(marker), "grandchild survived the group kill (streaming)"
    if os.path.exists(marker):
        os.remove(marker)


def test_streaming_stall_guard_kills_silent_cli():
    # Emits one line then goes silent far longer than no_output_timeout → killed as 'stalled',
    # well before the (much larger) outer timeout fires. Partial output is preserved.
    r = _run_stream(["sh", "-c", "echo hi; sleep 30"], 30,
                    on_line=lambda *a: None, no_output_timeout=1)
    assert not r.ok and r.kind == "stalled" and "hi" in r.output
