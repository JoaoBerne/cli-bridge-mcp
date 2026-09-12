# Agent guide — cli-bridge

Guidance for AI coding agents (Claude Code, Codex, Gemini CLI, opencode…) working on this
repo. `CLAUDE.md` is a symlink to this file.

## What this is

An MCP server that exposes the **other** AI CLIs on the machine as tools. Each lane spawns
the official CLI as a subprocess (no token extraction, no API keys). Read-only by
default. Pure-stdlib + `mcp` only. Default surface: 15 fixed tools + `ask_<lane>` per installed
CLI (`schemas.DEFAULT_TOOLS`, `CLI_BRIDGE_TOOLS` to widen).

## Layout

```
src/cli_bridge/
  server.py      # MCP surface: handlers, call_tool dispatch, hot path (_run_lane incl. spend gates), _run_workflow_preset table. Keep thin.
  mcp_compat.py  # the ONLY file that branches on the mcp SDK major (1.x decorators vs 2.x add_request_handler, renamed fields)
  schemas.py     # tool schemas (_tools_for/_ask_schema, shared _P params, DEFAULT_TOOLS + _filter_tools) — pure
  reports.py     # doctor/doctor_deep + _render_* markdown + setup recommendation (injected is_host/run_lane)
  prompts.py     # MCP prompts (apilookup)
  resources.py   # MCP resources: config, lane-stats, usage-summary (pure)
  lanes.py       # LaneSpec registry + argv builders + custom-lane JSON loader + PATH detection + model probes
  runner.py      # subprocess exec, redaction, ANSI cleanup, process-tree kill, error classification, pacing, streaming
  config.py      # env parsing (lane_env* for CLI_BRIDGE_<LANE>_*), cost profile, timeouts, INSTRUCTIONS
  telemetry.py   # sqlite3 run log + lane health/cooldown + cache + ratings/lessons (best-effort)
  router.py      # deterministic cascade / ask_best ordering (pure)
  council.py     # ask_all/ask_cascade/ask_best/synthesize fan-out (injected run_lane)
  jobs.py        # in-process async jobs (job tool) + sqlite persistence
  workflows.py   # review_diff (focus=code|security), debate (vote=judge|borda), premortem, test_plan, challenge, git_text, prechecks
  orchestrate.py # batch_run durable fan-out + presets refine_plan/map_review/research_verify/fanout_compare/converge
  findings.py    # parse/merge/render structured review findings (pure)
  guards.py      # injection/tool-poisoning output guard (CLI_BRIDGE_GUARD)
  worktrees.py   # ask_build (isolated worktree diff | direct zone-guarded write, in-process zone lock, artifact return)
  buildloop.py   # steerable multi-turn direct builds: job action=tail|steer, executable DoD gate
  conversations.py # round-table threads: sqlite transcript + recipient-aware replay + rolling summary
  preamble.py    # terse response-style preamble prepended to delegate prompts
  cli.py         # human/CI entry point (cli-bridge ...) over the same internals
  bridges/       # openai_compatible.py = cli-bridge-openai (urllib only; used by the applepcc lane and HTTP lanes)
tests/           # pytest; unit + cross-host integration (no real CLI needed)
benchmarks/      # eval harness (several models vs one), outside the package and CI: eval.py, tests/, fixtures/evalset/
docs/            # TOOLS, ARCHITECTURE, HOSTS, BUDGET, COSTS
examples/        # lane JSON recipes (local-runtime, apple-fm-serve, openai-compatible, community, free-apis), mcp.example.json, local-first-host.md
plugin/          # Claude Code plugin manifest (wires the MCP server; no skills)
assets/          # README banner/mark/social (generated, do not hand-edit)
```

## Rules for changes

- **Keep `server.py` thin** — business logic belongs in lanes/runner/router/telemetry/workflows.
- **No new runtime deps** beyond `mcp`. Stdlib only. `mcp>=1.2,<3`: every SDK-version branch
  stays in `mcp_compat.py`; run the suite on both majors before shipping.
- **Every change ships tests.** `pytest -q` must stay green. Tests must not need a real AI
  CLI or network (fake lanes via `echo`/`false`, temp sqlite via `CLI_BRIDGE_STATE_DB`).
- **Portability**: must run on macOS/Linux/Windows. No POSIX-only calls without a Windows
  branch (see `runner._kill_tree`).
- **Telemetry is best-effort** — it must NEVER raise into a delegation path. Its `tool=` labels
  in sqlite are stable across tool renames (old names stay as labels).
- **Cost safety**: a missing/empty model must never resolve to a paid model. `ask_all`/
  `ask_cascade`/`ask_best` exclude limited/paid by default.
- **Tool surface**: a removed tool becomes a parameter of one that stays; hosts cache tool
  names, so renames are BREAKING and go in the CHANGELOG with the replacement call.
- Match existing style; surgical diffs. Commits end with
  `Assisted-by: <model> <email>` (not `Co-Authored-By`).

## Commands

```
uv venv && uv pip install -e . pytest pytest-asyncio ruff
pytest -q
CLI_BRIDGE_STATE_DB=/tmp/t.sqlite pytest -q   # keep tests off your real state db
ruff check src/ tests/                        # lint (CI enforces this)
pip install 'mcp>=2,<3' && pytest -q          # the other SDK leg (CI runs both)
PYTHONPATH=src python benchmarks/eval.py      # offline scorer self-check; --live for real lanes
```

History lives in `CHANGELOG.md`; the module map with responsibilities is `docs/ARCHITECTURE.md`.
