"""Human CLI for cli-bridge — the same engine as the MCP server, runnable from a terminal or CI.

  cli-bridge doctor [--deep]
  cli-bridge ask <lane> <task...> [--model M] [--cwd DIR]
  cli-bridge ask-all <task...> [--synthesize] [--include-paid]
  cli-bridge ask-best <task...> [--mode fast|cheap|deep|code|review|security]
  cli-bridge build <lane> <task...> [--architect L] [--model M] [--cwd DIR]
  cli-bridge review-diff [--base REF] [--json] [--include-paid]
  cli-bridge security-review [--base REF] [--json]
  cli-bridge test-plan [--base REF] | cli-bridge premortem <task...>
  cli-bridge stats | usage [--since 24h] [--json] | budget | jobs
  cli-bridge setup [--write [PATH]]

Every command calls the SAME internal functions the MCP tools use, so behaviour matches. The
output guard is an MCP-host protection and is not applied here (a human reads the terminal).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys

from . import config, server, telemetry, workflows, worktrees
from . import eval as evals
from . import jobs as jobs_mod
from .detect import is_installed
from .lanes import all_lanes


def _lanes():
    return server._active_lanes()                  # host="" in the CLI (no MCP clientInfo)


def _targets(include_paid: bool):
    lanes, _ = _lanes()
    return server._ask_all_targets(lanes, include_paid)


def _cmd_doctor(a):
    lanes, host = _lanes()
    print(asyncio.run(server._doctor_deep(host, lanes)) if a.deep else server._doctor(host))


def _cmd_ask(a):
    lanes, _ = _lanes()
    lane = server._lane_by_key(a.lane, lanes)
    if not lane:
        sys.exit(f"[error] no such lane: {a.lane}. Run `cli-bridge doctor` to see installed lanes.")
    res = asyncio.run(server._run_lane(
        lane, {"task": " ".join(a.task), "model": a.model, "cwd": a.cwd, "timeout_s": a.timeout}))
    print(res.render())


def _cmd_ask_all(a):
    lanes, _ = _lanes()
    print(asyncio.run(server._ask_all_body(
        lanes, {"task": " ".join(a.task), "synthesize": a.synthesize,
                "include_paid": a.include_paid, "cwd": a.cwd})))


def _cmd_ask_best(a):
    lanes, _ = _lanes()
    out = asyncio.run(server._ask_best(
        lanes, {"task": " ".join(a.task), "mode": a.mode, "include_paid": a.include_paid,
                "cwd": a.cwd}))
    print(out[0].text)


def _cmd_build(a):
    lanes, _ = _lanes()
    lane = server._lane_by_key(a.lane, lanes)
    if not lane:
        sys.exit(f"[error] no such lane: {a.lane}. Run `cli-bridge doctor` to see installed lanes.")
    architect = None
    if a.architect:
        architect = server._lane_by_key(a.architect, lanes)
        if not architect:
            sys.exit(f"[error] no such architect lane: {a.architect}.")
    args = {"task": " ".join(a.task), "cwd": a.cwd, "model": a.model, "timeout_s": a.timeout}
    print(asyncio.run(worktrees.ask_build_isolated(lane, args, server._run_lane, architect)))


def _cmd_review(a):
    args = {"base": a.base, "cwd": a.cwd,
            "output_format": "json" if a.json else "markdown"}
    print(asyncio.run(workflows.review_diff(_targets(a.include_paid), args, server._run_lane)))


def _cmd_security(a):
    args = {"base": a.base, "cwd": a.cwd,
            "output_format": "json" if a.json else "markdown"}
    print(asyncio.run(workflows.security_review(_targets(a.include_paid), args, server._run_lane)))


def _cmd_test_plan(a):
    args = {"base": a.base, "cwd": a.cwd, "task": " ".join(a.task) if a.task else ""}
    print(asyncio.run(workflows.test_plan(_targets(a.include_paid), args, server._run_lane)))


def _cmd_premortem(a):
    args = {"task": " ".join(a.task), "include_paid": a.include_paid}
    print(asyncio.run(workflows.premortem(_targets(a.include_paid), args, server._run_lane)))


def _cmd_stats(a):
    print(server._render_lane_stats())


def _cmd_usage(a):
    rep = telemetry.usage_report(since_s=server._parse_since(a.since))
    print(json.dumps(rep, indent=2) if a.json else server._render_usage(rep))


def _cmd_budget(a):
    rep = telemetry.usage_budget()
    print(json.dumps(rep, indent=2) if a.json else server._render_budget(rep))


def _cmd_jobs(a):
    jobs_mod.mark_interrupted_on_startup()
    rows = jobs_mod.listing()
    print(json.dumps(rows, indent=2) if a.json else server._render_jobs_list(rows))


_ENV_TEMPLATE = """# cli-bridge configuration (source this, or set in your MCP server entry)
# Cost profile: saver=free only · balanced=paid when asked · max=best by default
CLI_BRIDGE_PROFILE={profile}
# Per-lane overrides (repeat per lane: GEMINI/GPT/CLAUDE/MISTRAL/OPENCODE/QWEN/COPILOT)
# CLI_BRIDGE_<LANE>_COST=free|limited|paid
# CLI_BRIDGE_<LANE>_ENABLED=false
# CLI_BRIDGE_<LANE>_MODEL=<model-id>
# CLI_BRIDGE_<LANE>_CREDITS_PER_1K=<credits per 1k tokens>   # for usage estimates
# CLI_BRIDGE_<LANE>_DAILY_LIMIT=<max runs/day>
# CLI_BRIDGE_<LANE>_MIN_INTERVAL_S=2   # anti-burst spawn pacing (free tier that rate-limits)
# Behaviour
CLI_BRIDGE_TERSE={terse}        # off|lite|full|ultra
CLI_BRIDGE_GUARD={guard}        # off|warn|strict
# CLI_BRIDGE_CACHE_TTL_S=0       # >0 enables the response cache
# CLI_BRIDGE_TRACE_FOOTER=off    # hide the JSON trace footer in workflow reports
"""


def _cmd_init(a):
    print("# cli-bridge init\n\nDetected CLIs on this machine:")
    for ln in all_lanes():
        mark = "✓ installed" if is_installed(ln) else "✗ not found"
        src = "set" if ln.cost_is_configured else "default"
        print(f"  {ln.key:9} {mark}  [{ln.cost_label} ({src})]"
              + (f"  (model: {ln.model_for('')})" if ln.model_for("") else ""))
    cmd = {"command": sys.executable, "args": ["-m", "cli_bridge"]}
    print("\nWire it into your MCP host over stdio. Claude Code:")
    print(f"  claude mcp add cli-bridge -- {sys.executable} -m cli_bridge")
    print("\nOr add to your client's mcpServers config:")
    print("  " + json.dumps({"cli-bridge": cmd}))
    print("\nThen pick a cost profile (CLI_BRIDGE_PROFILE=saver|balanced|max) and run `doctor`.")
    print("No CLIs yet? Set CLI_BRIDGE_MOCK=1 to explore everything with canned answers.")
    if a.probe:
        lanes, host = server._active_lanes()
        print("\nProbing free lanes live (uses a little quota)...\n")
        print(asyncio.run(server._doctor_deep(host, lanes)))


def _percentile(values, p):
    if not values:
        return 0
    s = sorted(values)
    i = min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))
    return s[i]


def _bench_one(lane, prompt, runs, model, timeout):
    lat, oks, out_chars = [], 0, 0
    for _ in range(runs):
        res = asyncio.run(server._run_lane(
            lane, {"task": prompt, "model": model, "timeout_s": timeout}))
        lat.append(res.latency_ms)
        if res.ok:
            oks += 1
            out_chars += len(res.output)
    return {
        "lane": lane.key, "model": lane.model_for(model), "runs": runs, "ok": oks,
        "ok_rate": round(oks / runs, 3) if runs else 0,
        "p50_ms": _percentile(lat, 50), "p95_ms": _percentile(lat, 95),
        "p99_ms": _percentile(lat, 99), "avg_ms": int(sum(lat) / len(lat)) if lat else 0,
        "est_output_tokens": out_chars // config.CHARS_PER_TOKEN,
    }


def _cmd_bench(a):
    lanes, _ = server._active_lanes()
    if a.all:
        targets = lanes if a.include_paid else [ln for ln in lanes
                                                if not ln.is_paid and not ln.is_limited]
        if not targets:
            sys.exit("[error] no lanes to benchmark. Run `cli-bridge doctor`.")
        reps = [_bench_one(ln, a.prompt, a.runs, "", a.timeout) for ln in targets]
        if a.json:
            print(json.dumps(reps, indent=2))
        else:
            print(f"# bench — {a.runs} runs/lane · prompt: {a.prompt[:50]!r}\n")
            print("| lane | ok | p50 ms | p95 ms | p99 ms | avg ms | ~out tok |")
            print("|------|----|-------:|-------:|-------:|-------:|---------:|")
            for r in reps:
                print(f"| {r['lane']} | {r['ok']}/{r['runs']} | {r['p50_ms']} | {r['p95_ms']} | "
                      f"{r['p99_ms']} | {r['avg_ms']} | {r['est_output_tokens']} |")
        return
    lane = server._lane_by_key(a.lane, lanes) if a.lane else None
    if not lane:
        sys.exit(f"[error] no such lane: {a.lane}. Use --all, or `cli-bridge doctor`.")
    r = _bench_one(lane, a.prompt, a.runs, a.model, a.timeout)
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        print(f"# bench {r['lane']} ({r['model'] or 'default'}) — {a.runs} runs")
        print(f"ok {r['ok']}/{a.runs} ({int(r['ok_rate'] * 100)}%) | "
              f"p50 {r['p50_ms']}ms · p95 {r['p95_ms']}ms · p99 {r['p99_ms']}ms · "
              f"avg {r['avg_ms']}ms | ~{r['est_output_tokens']} est out-tokens")


def _eval_calibration(fixtures) -> tuple[bool, list[str]]:
    """Offline self-check: the scorer must give full recall on every fixture's ideal findings
    (and zero false alarms on clean fixtures). Proves the SCORER before anyone trusts a live run."""
    ok = True
    rows = []
    for fx in fixtures:
        sc = evals.score_fixture(fx.ideal, fx)
        bad = (fx.bugs and sc.tp != sc.n_bugs) or sc.fp_decoy or sc.fp_other
        ok = ok and not bad
        mark = "FAIL" if bad else "ok"
        rows.append(f"  [{mark}] {fx.id:28} bugs={sc.n_bugs} caught={sc.tp} "
                    f"fp_decoy={sc.fp_decoy} fp_other={sc.fp_other}")
    return ok, rows


def _eval_resolve_lanes(keys, lanes, include_paid):
    out = []
    for k in keys:
        ln = server._lane_by_key(k, lanes)
        if not ln:
            sys.exit(f"[error] no such lane: {k}. Run `cli-bridge doctor` to see lanes.")
        if not include_paid and (ln.is_paid or ln.is_limited):
            print(f"[note] skipping {k}: paid/limited (pass --include-paid to allow)")
            continue
        out.append(ln)
    return out


def _cmd_eval(a):
    fixtures = evals.load_evalset(evals.evalset_dir(a.fixtures))
    if not fixtures:
        sys.exit("[error] no eval fixtures found. Pass --fixtures DIR or run from a checkout "
                 "(tests/fixtures/evalset).")
    live = a.live or os.environ.get("CLI_BRIDGE_EVAL_LIVE", "").lower() in {"1", "true", "yes"}

    if not live:
        summ = evals.corpus_summary(fixtures)
        ok, rows = _eval_calibration(fixtures)
        print(f"# cli-bridge eval — corpus self-check (offline)\n\n"
              f"{summ['fixtures']} fixtures · {summ['bugs']} reasoning bugs · "
              f"{summ['clean_fixtures']} clean (decoy) · categories: "
              f"{', '.join(summ['by_category'])}\n")
        print("\n".join(rows))
        print(f"\ncalibration: {'PASS' if ok else 'FAIL'} — "
              + ("the deterministic scorer credits every ideal finding."
                 if ok else "scorer regressed; fix before trusting a live run."))
        print("\nThis proves the SCORER, not the models. To MEASURE real models:\n"
              "  cli-bridge eval --live --council-lanes gpt,gemini,mistral,opencode "
              "--single-lane gpt --k 4 --repeats 5")
        sys.exit(0 if ok else 1)

    lanes, _ = server._active_lanes()
    council_keys = [k.strip() for k in (a.council_lanes or "").split(",") if k.strip()]
    if council_keys:
        council = _eval_resolve_lanes(council_keys, lanes, a.include_paid)
    else:
        council = [ln for ln in lanes if is_installed(ln)
                   and (a.include_paid or not (ln.is_paid or ln.is_limited))][:4]
    if len(council) < 2:
        sys.exit("[error] need at least 2 council lanes. Install/login more CLIs or name them "
                 "with --council-lanes.")
    single = (_eval_resolve_lanes([a.single_lane], lanes, a.include_paid) or [None])[0] \
        if a.single_lane else council[0]
    if not single:
        sys.exit("[error] single lane unavailable.")
    k = a.k or len(council)
    print(f"[eval] live · council={[ln.key for ln in council]} · single={single.key}×{k} · "
          f"repeats={a.repeats} · {len(fixtures)} fixtures (this spends real quota)\n",
          file=sys.stderr)
    res = asyncio.run(evals.evaluate(
        fixtures, council, single, k=k, run_lane=server._run_lane, repeats=a.repeats,
        include_prechecks=a.include_prechecks, timeout_s=a.timeout))
    print(json.dumps(evals.result_dict(res), indent=2) if a.json else evals.render_markdown(res))


def _cmd_setup(a):
    print(config.SETUP_TEXT)
    if a.write is None:
        return
    path = a.write or "cli-bridge.env"
    import os
    if os.path.exists(path):
        backup = path + ".bak"
        shutil.copy2(path, backup)              # never overwrite without a backup
        print(f"\nBacked up existing {path} -> {backup}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_ENV_TEMPLATE.format(profile=config.profile(), terse="lite", guard="warn"))
    print(f"Wrote an example config to {path}. Edit it to match your plans, then source it.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cli-bridge",
                                description="Consult a council of AI CLIs from your terminal.")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="show installed CLIs, host, cost profile")
    d.add_argument("--deep", action="store_true", help="live-probe each free lane's auth")
    d.set_defaults(func=_cmd_doctor)

    ask = sub.add_parser("ask", help="ask one lane")
    ask.add_argument("lane")
    ask.add_argument("task", nargs="+")
    ask.add_argument("--model", default="")
    ask.add_argument("--cwd", default="")
    ask.add_argument("--timeout", type=int, default=None)
    ask.set_defaults(func=_cmd_ask)

    aa = sub.add_parser("ask-all", help="ask every free lane in parallel")
    aa.add_argument("task", nargs="+")
    aa.add_argument("--synthesize", action="store_true")
    aa.add_argument("--include-paid", dest="include_paid", action="store_true")
    aa.add_argument("--cwd", default="")
    aa.set_defaults(func=_cmd_ask_all)

    ab = sub.add_parser("ask-best", help="pick the best lane for the job")
    ab.add_argument("task", nargs="+")
    ab.add_argument("--mode", default="cheap", choices=list(server.router.MODES))
    ab.add_argument("--include-paid", dest="include_paid", action="store_true")
    ab.add_argument("--cwd", default="")
    ab.set_defaults(func=_cmd_ask_best)

    bd = sub.add_parser("build", help="delegate a real build to a lane in a throwaway worktree → "
                                      "diff (your repo is NEVER modified)")
    bd.add_argument("lane")
    bd.add_argument("task", nargs="+")
    bd.add_argument("--architect", default="",
                    help="optional stronger lane writes a plan first; the build lane implements it")
    bd.add_argument("--model", default="")
    bd.add_argument("--cwd", default="")
    bd.add_argument("--timeout", type=int, default=None)
    bd.set_defaults(func=_cmd_build)

    for nm, fn, h in (("review-diff", _cmd_review, "multi-model code review of a git diff"),
                      ("security-review", _cmd_security, "OWASP-aware security review")):
        rv = sub.add_parser(nm, help=h)
        rv.add_argument("--base", default="")
        rv.add_argument("--cwd", default="")
        rv.add_argument("--json", action="store_true", help="structured JSON output")
        rv.add_argument("--include-paid", dest="include_paid", action="store_true")
        rv.set_defaults(func=fn)

    tp = sub.add_parser("test-plan", help="derive a test plan from the diff")
    tp.add_argument("task", nargs="*")
    tp.add_argument("--base", default="")
    tp.add_argument("--cwd", default="")
    tp.add_argument("--include-paid", dest="include_paid", action="store_true")
    tp.set_defaults(func=_cmd_test_plan)

    pm = sub.add_parser("premortem", help="stress-test a plan before building")
    pm.add_argument("task", nargs="+")
    pm.add_argument("--include-paid", dest="include_paid", action="store_true")
    pm.set_defaults(func=_cmd_premortem)

    sub.add_parser("stats", help="per-lane health").set_defaults(func=_cmd_stats)

    us = sub.add_parser("usage", help="estimated usage report")
    us.add_argument("--since", default="")
    us.add_argument("--json", action="store_true")
    us.set_defaults(func=_cmd_usage)

    bg = sub.add_parser("budget", help="today's usage vs daily limits")
    bg.add_argument("--json", action="store_true")
    bg.set_defaults(func=_cmd_budget)

    jb = sub.add_parser("jobs", help="recent async jobs")
    jb.add_argument("--json", action="store_true")
    jb.set_defaults(func=_cmd_jobs)

    it = sub.add_parser("init", help="detect CLIs + print MCP wiring + cost hint")
    it.add_argument("--probe", action="store_true", help="also live-probe free lanes")
    it.set_defaults(func=_cmd_init)

    bn = sub.add_parser("bench", help="benchmark a lane (or --all): latency p50/p95/p99 over N runs")
    bn.add_argument("--lane", default="")
    bn.add_argument("--all", action="store_true", help="benchmark every free lane → table")
    bn.add_argument("--prompt", required=True)
    bn.add_argument("--runs", type=int, default=5)
    bn.add_argument("--model", default="")
    bn.add_argument("--include-paid", dest="include_paid", action="store_true")
    bn.add_argument("--timeout", type=int, default=None)
    bn.add_argument("--json", action="store_true")
    bn.set_defaults(func=_cmd_bench)

    evp = sub.add_parser("eval", help="quality eval: council vs single model + self-consistency")
    evp.add_argument("--live", action="store_true",
                     help="spend real quota to measure models (default: offline self-check only)")
    evp.add_argument("--council-lanes", dest="council_lanes", default="",
                     help="comma-separated lanes for the council arm (default: free installed)")
    evp.add_argument("--single-lane", dest="single_lane", default="",
                     help="lane for the single+self-consistency arm (default: first council lane)")
    evp.add_argument("--k", type=int, default=0, help="self-consistency samples (default: =council size)")
    evp.add_argument("--repeats", type=int, default=3, help="repeats for mean±sd (use 5 to publish)")
    evp.add_argument("--fixtures", default="", metavar="DIR", help="eval corpus dir override")
    evp.add_argument("--include-paid", dest="include_paid", action="store_true")
    evp.add_argument("--include-prechecks", dest="include_prechecks", action="store_true",
                     help="count deterministic precheck findings (identical in both arms)")
    evp.add_argument("--timeout", type=int, default=None)
    evp.add_argument("--json", action="store_true")
    evp.set_defaults(func=_cmd_eval)

    st = sub.add_parser("setup", help="cost-profile guidance; --write an example config")
    st.add_argument("--write", nargs="?", const="", default=None, metavar="PATH",
                    help="write an example config file (backs up any existing one first)")
    st.set_defaults(func=_cmd_setup)

    return p


def main(argv: list[str] | None = None) -> None:
    config.apply_file_config_to_env()   # JSON config fills any unset env var (env still wins)
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
