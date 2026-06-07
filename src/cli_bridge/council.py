"""The lane council: fan-out (`ask_all`), cheapest→strongest fallback (`ask_cascade`), and
mode-routed single-best (`ask_best`) — plus the optional second-pass `synthesize`.

Decoupled from server.py on purpose (the same pattern as workflows.py): every function takes
its host couplings as injected callables — `run_lane` (spawn a lane), `emit` (guard + spill big
output), `progress` (live "k/N done"), `host_sample` (free host-model judge) — and the cost
policy helpers (`include_paid_fn`/`targets_fn`/`timeout_fn`) stay in server.py, shared by the
rest of dispatch. So this module is unit-testable with fakes (no real CLI, no network) and
server.py keeps only thin glue.
"""
from __future__ import annotations

import asyncio
import json

from . import config, router, runner, telemetry, workflows
from .config import ASK_ALL_SYNTH_TIMEOUT_S
from .lanes import LaneSpec

try:
    from mcp.types import TextContent
except Exception:  # pragma: no cover - mcp is always present at runtime
    TextContent = None  # type: ignore[assignment,misc]


def _s(args: dict, key: str) -> str:
    """Coerce an arg to a clean string. JSON-RPC callers often send null -> must not become
    the literal 'None'."""
    val = args.get(key)
    return str(val).strip() if val is not None else ""


# ── cascade (cheapest → strongest, stop at first success) ──────────────────────────────────

async def ask_cascade(lanes: list[LaneSpec], args: dict, *, run_lane, emit) -> list[TextContent]:
    task = _s(args, "task")
    if not task:
        return [TextContent(type="text", text="[error] task is required")]
    include_paid = (bool(args["include_paid"]) if args.get("include_paid") is not None
                    else config.profile() == "max")
    ordered = router.order_lanes(lanes, telemetry.cooldown_remaining, include_paid)
    if not ordered:
        return [TextContent(type="text", text=(
            "[error] no lanes eligible for cascade. Install/login a CLI, or set include_paid=true "
            "/ CLI_BRIDGE_PROFILE=max to allow limited/paid lanes."))]
    sub = {"task": task, "cwd": _s(args, "cwd"), "timeout_s": args.get("timeout_s")}
    chosen, attempts = await run_chain(ordered, sub, "ask_cascade", run_lane=run_lane)
    if chosen is not None:
        res = next(r for ln, r in attempts if ln is chosen)
        return [emit(f"{res.output}\n\n{cascade_trace(attempts, chosen=chosen)}",
                     label="ask_cascade")]
    return [TextContent(type="text", text=(
        "[error] all lanes failed in cascade: "
        + ", ".join(f"{ln.key}={r.kind}" for ln, r in attempts)
        + ". Try again later or check `doctor`.\n\n" + cascade_trace(attempts, chosen=None)))]


async def run_chain(ordered: list[LaneSpec], sub: dict, tool: str, *, run_lane
                    ) -> tuple[LaneSpec | None, list[tuple[LaneSpec, runner.RunResult]]]:
    """Try lanes in order, stop at the first success. Shared by ask_cascade and ask_best."""
    attempts: list[tuple[LaneSpec, runner.RunResult]] = []
    for lane in ordered:
        res = await run_lane(lane, sub, tool=tool)
        attempts.append((lane, res))
        if res.ok:
            return lane, attempts
    return None, attempts


# ── best (route by mode, then cascade within the ordered list) ─────────────────────────────

async def ask_best(lanes: list[LaneSpec], args: dict, *, run_lane, emit) -> list[TextContent]:
    task = _s(args, "task")
    if not task:
        return [TextContent(type="text", text="[error] task is required")]
    mode = _s(args, "mode").lower() or "cheap"
    if mode not in router.MODES:
        return [TextContent(type="text", text=(
            f"[error] unknown mode '{mode}'. Choose one of: {', '.join(router.MODES)}."))]
    include_paid = (bool(args["include_paid"]) if args.get("include_paid") is not None
                    else config.profile() == "max")
    perf = telemetry.lane_perf()
    quality = telemetry.lane_quality(mode)
    ordered = router.order_for_mode(lanes, telemetry.cooldown_remaining, lambda k: perf.get(k, {}),
                                    mode, include_paid, quality_of=lambda k: quality.get(k, {}))
    if not ordered:
        return [TextContent(type="text", text=(
            f"[error] no lanes eligible for mode '{mode}'. Install/login a CLI, or widen with "
            "include_paid=true / CLI_BRIDGE_PROFILE=max."))]
    sub = {"task": task, "cwd": _s(args, "cwd"), "timeout_s": args.get("timeout_s")}
    chosen, attempts = await run_chain(ordered, sub, "ask_best", run_lane=run_lane)
    if chosen is not None:
        res = next(r for ln, r in attempts if ln is chosen)
        trace = cascade_trace(attempts, chosen=chosen).replace("cheapest→strongest", f"mode '{mode}'")
        hint = (f"\n_Tip: `rate_lane(lane=\"{chosen.key}\", mode=\"{mode}\", score=1..5)` to teach "
                "the router which lane wins this kind of task on your machine._")
        return [emit(f"{res.output}\n\n{trace}{hint}", label="ask_best")]
    return [TextContent(type="text", text=(
        f"[error] all lanes failed for mode '{mode}': "
        + ", ".join(f"{ln.key}={r.kind}" for ln, r in attempts)
        + ". Check `doctor`.\n\n" + cascade_trace(attempts, chosen=None)))]


def cascade_trace(attempts: list[tuple[LaneSpec, runner.RunResult]],
                  chosen: LaneSpec | None) -> str:
    """Compact, honest record of what the cascade did: order tried (cheapest→strongest),
    each lane's cost tier + latency, why it was skipped, and which one answered."""
    lines = ["---", "_Trace — cascade (cheapest→strongest):_"]
    for lane, res in attempts:
        if chosen is not None and lane is chosen:
            lines.append(f"- ✅ **{lane.key}** [{lane.cost_label}] {res.latency_ms}ms — chosen")
        else:
            lines.append(f"- ❌ {lane.key} [{lane.cost_label}] {res.latency_ms}ms — {res.kind}")
    return "\n".join(lines)


# ── fan-out (ask_all) ──────────────────────────────────────────────────────────────────────

async def ask_all_body(lanes: list[LaneSpec], args: dict, *, run_lane, progress, host_sample,
                       include_paid_fn, targets_fn, timeout_fn) -> str:
    """The fan-out itself, returning the report as a plain string so it can run either inline
    (ask_all) or inside a background job (ask_all_async)."""
    # Explicit arg wins. Otherwise the cost profile decides: 'max' polls paid lanes too,
    # saver/balanced stay free-only by default (the caller can still pass include_paid).
    include_paid = include_paid_fn(args)
    targets = targets_fn(lanes, include_paid)
    if not targets:
        held = [ln.display for ln in lanes if ln.is_paid or ln.is_limited]
        if held:
            return ("[error] no FREE lanes to fan out to. Limited/paid lanes available: "
                    f"{', '.join(held)}. Call ask_all with include_paid=true, or mark a lane "
                    "free for your plan via CLI_BRIDGE_<LANE>_COST=free.")
        return ("[error] no delegate CLIs installed. Run `doctor` to see install hints, "
                "then install/log into at least one CLI (e.g. gemini, mistral, opencode).")
    out_fmt = _s(args, "output_format").lower() or "markdown"
    task = _s(args, "task")
    if bool(args.get("dry_run")):              # preview cost/lanes WITHOUT spawning anything
        return ask_all_plan(targets, task, out_fmt)
    sub = {"task": task, "cwd": _s(args, "cwd"),
           "timeout_s": timeout_fn(args.get("timeout_s"))}
    # Cap simultaneous spawns so a wide council (many custom lanes) can't OOM a small machine
    # or burst quota. Default high enough that a normal free council is unaffected. The semaphore
    # is created in the running loop (per call) to stay safe across separate event loops.
    sem = asyncio.Semaphore(config.max_parallel())
    total = len(targets)
    done = 0
    prog_lock = asyncio.Lock()

    async def _capped(ln):
        async with sem:
            r = await run_lane(ln, sub)
        nonlocal done
        async with prog_lock:
            done += 1
            d = done
        await progress(d, total, ln.display)   # live "k/N lanes done" if host asked
        return r
    # return_exceptions: one broken lane must not sink the whole fan-out.
    results = await asyncio.gather(*[_capped(ln) for ln in targets], return_exceptions=True)
    blocks = []
    rows = []
    for lane, res in zip(targets, results, strict=False):
        if isinstance(res, BaseException):
            blocks.append(f"## {lane.display} - FAILED (crash)\n\n[crash] {res}")
            rows.append((lane.display, False, 0, f"crash: {res}"))
        else:
            status = "OK" if res.ok else f"FAILED ({res.kind})"
            blocks.append(f"## {lane.display} - {status} _[{lane.cost_label}, {res.latency_ms}ms]_"
                          f"\n\n{res.render()}")
            rows.append((lane.display, res.ok, res.latency_ms,
                         res.output if res.ok else res.kind))
    skipped = [ln.display for ln in lanes if (ln.is_paid or ln.is_limited) and not include_paid]
    footer = (f"\n\n---\n_Skipped limited/paid lanes: {', '.join(skipped)} "
              f"(set include_paid=true)._"
              if skipped else "")
    synth = ""
    if bool(args.get("synthesize")):
        ok = [(lane, res) for lane, res in zip(targets, results, strict=False)
              if not isinstance(res, BaseException) and res.ok]
        synth = await synthesize(task, ok, targets, run_lane=run_lane, host_sample=host_sample)

    if out_fmt == "json":                      # structured output for CI / IDE / automation
        return json.dumps({
            "tool": "ask_all", "task": task,
            "lanes": [
                {"lane": lane.display, "ok": bool(getattr(res, "ok", False)),
                 "kind": getattr(res, "kind", "crash"),
                 "latency_ms": getattr(res, "latency_ms", 0),
                 "output": (res.output if not isinstance(res, BaseException) and res.ok
                            else (getattr(res, "output", "") or str(res)))}
                for lane, res in zip(targets, results, strict=False)],
            "synthesis": synth or None,
            "skipped": skipped,
        }, indent=2)

    # Recap first so the host gets an at-a-glance digest of every lane before the full blocks.
    recap = workflows.council_recap(rows, title="Council")
    if bool(args.get("summary_only")):         # recap + synthesis only — skip the raw blocks (tokens-)
        body = recap + footer
    else:
        body = recap + "\n\n" + "\n\n".join(blocks) + footer
    if synth:
        body += f"\n\n---\n## Synthesis (agreement / disagreement)\n\n{synth}"
    return body


def ask_all_plan(targets: list[LaneSpec], task: str, out_fmt: str) -> str:
    """dry_run preview: which lanes would be queried + a rough ESTIMATED token/credit cost,
    without spawning anything. chars/4 input estimate × lanes (output unknown, so input-only)."""
    in_tok = max(1, len(task) // config.CHARS_PER_TOKEN)
    rows = [{"lane": ln.display, "cost": ln.cost_label, "est_input_tokens": in_tok} for ln in targets]
    if out_fmt == "json":
        return json.dumps({"tool": "ask_all", "dry_run": True, "lanes": rows,
                           "est_input_tokens_total": in_tok * len(targets),
                           "note": "estimate only (chars/4); output tokens unknown until run"},
                          indent=2)
    lines = [f"# ask_all — dry run ({len(targets)} lanes, nothing spawned)", "",
             f"_Each lane gets ~{in_tok} input tokens (est, chars/4); output adds more._\n"]
    for r in rows:
        lines.append(f"- {r['lane']} [{r['cost']}]")
    return "\n".join(lines)


async def synthesize(question, answered, targets, *, run_lane, host_sample) -> str:
    """Second pass: read all answers and flag agreement/disagreement. Prefers the HOST's own
    model (MCP sampling — free, no lane spent); falls back to the cheapest free lane. Returns ''
    if neither can do it."""
    if len(answered) < 2:
        return ""
    transcript = "\n\n".join(f"### {lane.display}\n{res.output}" for lane, res in answered)
    prompt = (
        "Several AI models answered the same question. Summarize concisely: (1) where they "
        "AGREE, (2) where they DISAGREE (name which model said what), (3) the most reliable "
        f"takeaway. Be brief.\n\nQUESTION:\n{question}\n\nANSWERS:\n{transcript}")
    # Prefer the host's own model — free, no lane spawned, no quota.
    via_host = await host_sample(prompt, max_tokens=800)
    if via_host:
        return f"{via_host}\n\n_(synthesized by your host model via MCP sampling — no lane spent)_"
    judge = next((ln for ln in targets
                  if not ln.is_paid and not ln.is_limited and not ln.experimental), None)
    if judge is None:
        return ""
    res = await run_lane(judge, {"task": prompt, "timeout_s": ASK_ALL_SYNTH_TIMEOUT_S})
    return res.output if res.ok else ""
