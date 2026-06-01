# Agent guide — cli-bridge

Guidance for AI coding agents (Claude Code, Codex, Gemini CLI, opencode…) working on this
repo. `CLAUDE.md` is a symlink to this file.

## What this is

An MCP server that lets the host AI consult **other** AI CLIs as a council. Each lane spawns
the official CLI as a subprocess (ban-safe: no token extraction, no API keys). Read-only by
default. Pure-stdlib + `mcp` only.

## Layout

```
src/cli_bridge/
  server.py     # MCP surface: tool list, dispatch, doctor/setup. Keep thin.
  lanes.py      # LaneSpec registry + argv builders + custom-lane JSON loader
  runner.py     # subprocess exec, redaction, process-tree kill, error classification
  config.py     # env parsing, cost profile, timeouts, onboarding text
  telemetry.py  # sqlite3 run log + lane health/cooldown (best-effort, privacy-first)
  router.py     # deterministic cascade ordering (pure)
  jobs.py       # in-process async jobs (ask_all_async) + sqlite persistence
  workflows.py  # review_diff/security_review/debate + prechecks + council recap
  findings.py   # parse/merge/render structured review findings (pure)
  guards.py     # injection/tool-poisoning output guard (CLI_BRIDGE_GUARD)
  worktrees.py  # ask_build_isolated: write mode in a throwaway git worktree
  detect.py     # PATH detection
tests/          # pytest; unit + cross-host integration (no real CLI needed)
```

## Rules for changes

- **Keep `server.py` thin** — business logic belongs in lanes/runner/router/telemetry.
- **No new runtime deps** beyond `mcp`. Stdlib only.
- **Every change ships tests.** `pytest -q` must stay green. Tests must not need a real AI
  CLI or network (fake lanes via `echo`/`false`, temp sqlite via `CLI_BRIDGE_STATE_DB`).
- **Portability**: must run on macOS/Linux/Windows. No POSIX-only calls without a Windows
  branch (see `runner._kill_tree`).
- **Telemetry is best-effort** — it must NEVER raise into a delegation path.
- **Cost safety**: a missing/empty model must never resolve to a paid model. `ask_all`/
  `ask_cascade` exclude limited/paid by default.
- Match existing style; surgical diffs.

## Commands

```
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q
CLI_BRIDGE_STATE_DB=/tmp/t.sqlite pytest -q   # keep tests off your real state db
```

## Roadmap

See `SOTA_ACTION_PLAN.md`. Done: config extraction, telemetry+cooldown, cascade router,
terse preamble (+min-chars skip), response cache, trace fields, workflow tools (review_diff/
security_review/debate), council recap, MCP prompts, opt-in write/build mode (all lanes),
sibling-model self-consultation, in-process async jobs (ask_all_async), structured findings
JSON + deterministic merge + prechecks + residual_risk, output guard (injection/poisoning),
worktree-isolated write mode (ask_build_isolated), ask_best mode router + estimated token/
credit accounting (usage_report/usage_budget).
Next candidates: human CLI, MCP resources, premortem/test_plan workflows, evals + lint, PyPI.
