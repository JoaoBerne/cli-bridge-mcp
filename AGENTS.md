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
  conversations.py # round-table threads: sqlite persistence + recipient-aware replay
  preamble.py   # terse response-style preamble prepended to delegate prompts
  eval.py       # quality eval: council vs single + self-consistency, deterministic scorer
  cli.py        # human/CI entry point (cli-bridge ...) over the same internals
  detect.py     # PATH detection
tests/          # pytest; unit + cross-host integration (no real CLI needed)
docs/           # COSTS.md, BENCHMARKS.md, ARCHITECTURE.md, i18n/ READMEs
assets/         # README banner/mark/social SVGs + demo.gif (generated, do not hand-edit)
site/           # GitHub Pages landing (deployed by .github/workflows/pages.yml)
examples/       # custom-lane JSON recipes + GitHub Action
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
uv venv && uv pip install -e . pytest pytest-asyncio ruff
pytest -q
CLI_BRIDGE_STATE_DB=/tmp/t.sqlite pytest -q   # keep tests off your real state db
ruff check src/ tests/                        # lint (CI enforces this)
CLI_BRIDGE_LIVE_E2E=1 pytest tests/test_live_e2e.py -q   # opt-in live checks
```

## Roadmap

See `CHANGELOG.md` for the shipped history. Done: config extraction, telemetry+cooldown, cascade router,
terse preamble (+min-chars skip), response cache, trace fields, workflow tools (review_diff/
security_review/debate), council recap, MCP prompts, opt-in write/build mode (all lanes),
sibling-model self-consultation, in-process async jobs (ask_all_async), structured findings
JSON + deterministic merge + prechecks + residual_risk, output guard (injection/poisoning),
worktree-isolated write mode (ask_build_isolated), ask_best mode router + estimated token/
credit accounting (usage_report/usage_budget), human CLI (cli-bridge), MCP resources,
premortem/test_plan workflows, eval fixtures + no-network evaluator, ruff lint + CI lint job,
modular tool loading (DISABLED_TOOLS/ENABLED_TOOLS), quality eval (`cli-bridge eval`: council vs
single-model + self-consistency, deterministic scorer + calibration gate), architect/editor build
split, debate VOTE footer + convergence early-stop, files_required grounding gate, anti-burst
spawn pacing (per-lane MIN_INTERVAL_S), trace-footer toggle, i18n READMEs (docs/i18n/), Pages
landing (site/), opt-in streaming runner (arun on_line/log_path + stall guard), direct builds
(ask_build mode=isolated|direct — zone contract + per-zone lock + post-turn zone-violation check +
greenfield init), steerable multi-turn builds (buildloop: job_tail/build_steer/interrupt, executable
DoD gate, plan-leak warning), durable journaled fan-out (batch_run + resume_id across restart) with
workflow presets (council_review/map_review/research_verify/refine_plan), guard NFKC/zero-width
normalization, runtime paid-model warning.
Next candidates: forced-pacing workflow engine, extract the ask_all/cascade/best fan-out
from server.py into a council module (the workflows.py pattern: injected run_lane/progress), mypy
gate in CI (~50 errors today, mostly MCP-SDK stub mismatches), eval v3 (permutation test instead
of the 1-sigma overlap heuristic; multi-bug/multi-language fixtures; decoys inside buggy
fixtures), native build resume (--session-id) + intra-turn streaming tail, chars/token calibration
per lane, opt-in real-CLI contract job in CI, release docs, history scrub, PyPI publish.
