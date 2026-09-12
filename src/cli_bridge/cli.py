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

Every command calls the SAME internal functions the MCP tools use, so behaviour matches. The
output guard is an MCP-host protection and is not applied here (a human reads the terminal).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import config, server, telemetry, workflows, worktrees
from . import jobs as jobs_mod


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
    args = {"task": " ".join(a.task), "cwd": a.cwd, "model": a.model, "timeout_s": a.timeout,
            "apply": a.apply}
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


def _cmd_set_cost(a):
    if a.cost not in ("free", "limited", "paid"):
        sys.exit("[error] cost must be free, limited or paid")
    lane = a.lane.strip().lower()
    fields = {"cost": a.cost}
    if a.note:
        fields["cost_note"] = a.note[:200]
    path = config.update_config_file({lane: fields})
    if not path:
        sys.exit("[error] config file not writable")
    print(f"Lane '{lane}' cost set to '{a.cost}' — persisted to {path}.")
    env_key = lane.upper().replace("-", "_")
    import os
    if f"CLI_BRIDGE_{env_key}_COST" in os.environ:
        print(f"⚠️ CLI_BRIDGE_{env_key}_COST is set in your environment — env wins over the "
              "config file; unset it for this value to apply.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cli-bridge",
                                description="Consult a council of AI CLIs from your terminal.")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="show installed CLIs, host, cost profile")
    d.add_argument("--deep", action="store_true", help="live-probe each free lane's auth")
    d.set_defaults(func=_cmd_doctor)

    sc = sub.add_parser("set-cost", help="record what a lane costs YOU (persists to the config file)")
    sc.add_argument("lane", help="lane key (see doctor)")
    sc.add_argument("cost", choices=["free", "limited", "paid"])
    sc.add_argument("--note", default="", help="one line saying who/what established this")
    sc.set_defaults(func=_cmd_set_cost)

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
                                      "diff (repo untouched unless --apply)")
    bd.add_argument("lane")
    bd.add_argument("task", nargs="+")
    bd.add_argument("--architect", default="",
                    help="optional stronger lane writes a plan first; the build lane implements it")
    bd.add_argument("--model", default="")
    bd.add_argument("--cwd", default="")
    bd.add_argument("--timeout", type=int, default=None)
    bd.add_argument("--apply", action="store_true",
                    help="apply the diff to your repo as unstaged changes (git apply --check "
                         "first; a conflict applies nothing)")
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

    return p


def main(argv: list[str] | None = None) -> None:
    config.apply_file_config_to_env()   # JSON config fills any unset env var (env still wins)
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
