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
  server.py     # MCP surface: @decorators, call_tool dispatch, hot path (_run_lane), request-context glue. Keep thin.
  schemas.py    # tool-schema assembly (_tools_for/_ask_schema/_filter_tools) — pure, re-exported by server
  reports.py    # doctor/doctor_deep + _render_* markdown + setup recommendation (injected is_host/run_lane)
  prompts.py    # MCP prompt builders + _PROMPTS registry (host-native slash commands, pure)
  resources.py  # MCP resource payloads: config snapshot + review-result JSON schema (pure)
  lanes.py      # LaneSpec registry + argv builders + custom-lane JSON loader
  runner.py     # subprocess exec, redaction, process-tree kill, error classification
  config.py     # env parsing, cost profile, timeouts, onboarding text
  telemetry.py  # sqlite3 run log + lane health/cooldown (best-effort, privacy-first)
  router.py     # deterministic cascade ordering (pure)
  council.py    # ask_all/ask_cascade/ask_best/synthesize fan-out (injected run_lane — like workflows)
  jobs.py       # in-process async jobs (ask_all_async) + sqlite persistence
  workflows.py  # review_diff/security_review/debate + prechecks + council recap
  orchestrate.py # batch_run durable fan-out + presets (refine_plan/verify_repair/fanout_compare/converge)
  consensus_loop.py # converge-loop PURE state machine (3 governance guards, no I/O) — driven by orchestrate
  findings.py   # parse/merge/render structured review findings (pure; optional category taxonomy)
  guards.py     # injection/tool-poisoning output guard (CLI_BRIDGE_GUARD)
  worktrees.py  # ask_build (isolated worktree diff | direct zone-guarded write + artifact return)
  buildloop.py  # steerable multi-turn builds: job_tail/build_steer, executable DoD gate
  conversations.py # round-table threads: sqlite persistence + recipient-aware replay
  preamble.py   # terse response-style preamble prepended to delegate prompts
  eval.py       # quality eval: council vs single + self-consistency, permutation test, scorer
  cli.py        # human/CI entry point (cli-bridge ...) over the same internals
  detect.py     # PATH detection (+ availability_env gate for opt-in API lanes)
  bridges/      # bundled stdlib API bridges (openai_compatible.py = cli-bridge-openai, urllib-only)
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
normalization, runtime paid-model warning, **council module extraction** (`council.py`, injected
run_lane), **mypy gate in CI** (typed `_ann()` helper for the SDK-stub noise), **eval v3** (seeded
permutation test replacing the 1-sigma heuristic + multi-bug fixtures + in-fixture decoys),
**build artifact-return** (non-text files surfaced by path — capability-borrowing), **cross-model
`verify_repair`** + **`fanout_compare`** workflow presets. **Dynamic orchestration engine (Phase 1):**
typed result envelope + provenance, `findings.extract_json` contract, per-invocation budget caps +
`dry_run` cost envelope, **cross-vendor `jury`** (author≠reviewer family, k-of-N fail-closed) +
`lanes.family_of`, **disagreement-as-uncertainty** score on `ask_all`, opt-in **confidence-escalate**
cascade, **`BRIDGE_DEPTH` re-entry guard**, **`CLI_BRIDGE_LEAN`** core surface, `role=` personas,
Gemini `images=` vision (experimental). **Local + council quality + quota resilience:** **Ollama lane**
(`ask_ollama`/`list_ollama_models` — local, $0, offline, read-only) + local-model custom-lane recipes
(`examples/`), **peer-anonymized debate/council** (neutral Reviewer/Debater labels so no model favours
a known rival), **`seat_report`** earn-their-seat (`jury_outcomes` telemetry benches dead-weight lanes
on evidence), **discrete calibration binning** (eval bins on emitted confidences, N≥50 gate),
**quota-empty cooldown with capped exponential backoff** (never infinite, success-resets).
**Governance + classification:** **optional issue-category taxonomy** on findings (`{security,
correctness, scope, ambiguity, performance, ops}`, orthogonal to severity, never invented),
**`workflow preset=converge`** governance loop — a PURE state machine (`consensus_loop.py`)
enforcing blind-verdict-first + no-silent-dismissal + no-self-approval in code (author → blind
arbiter → anonymized cross-family peers → reasoned adjudication → revise/converge), **opt-in API
lanes** (`availability_env` auto-hides a lane until its key is set; bundled `cli-bridge-openai`
urllib bridge + built-in `openrouter`; ban-safe default unchanged), **read-only mutation guard**
(`CLI_BRIDGE_VERIFY_PLAN_READONLY` flags a plan-mode delegate that writes to a git workspace; no
auto-revert).

### Considered & deferred (rationale — not just "not yet")
- **forced-pacing engine** — contradicts the model (cli-bridge delegates investigation to the
  council; it doesn't force the host to slow down), big effort, low value, and only helps if the
  host respects the gate. Dropped.
- **warm pool** — no lane offers a daemon/server mode (the lanes are spawn-per-call), so there's
  nothing to keep warm. Infeasible cleanly.
- **chars/token calibration per lane** — would need real provider token counts = ban-risk fishing,
  against the no-extraction ethos. The chars/4 figure stays honestly labeled "estimated".
- **native build resume (`--session-id`)** — no lane exposes a reliable session id; filesystem
  continuity (the delegate re-reads its own files each turn) already covers it. Revisit if a CLI
  ships a stable resume handle.
- **Big orchestration architecture** (recursive spawn trees, shared state bus, inter-agent mailbox,
  capability passthrough hub, a wire-protocol "bus between AIs") — real directions, but vaporware-
  prone and vendor-hostile (we build on CLIs we don't control). Roadmap only; positioned honestly
  as a direction, never sold as a shipped protocol. See `docs/ARCHITECTURE.md` for the framing.

### Next candidates (small — after real-usage soak of the engine; council-trimmed)
- **early-stop `ask_all`** (`agree_stop`) — stop spawning once K lanes agree (reuses the agreement
  score). Deferred: needs ask_all restructured from gather-all to incremental + cancellation, and
  the agreement heuristic validated on real outputs first.
- **architect/editor split** for `ask_build` (plan on a strong lane, edit on a cheap diff-precise one).
- GATED (build on real demand, not speculatively): **planner → plan_build**, **precommit** (≈
  `review_diff role=strict`), **MoA** preset. CUT: **debug**, **conversation_resume**, generic
  chaining **DSL** / **recursive spawn** (the host already orchestrates; see deferred above).
- Release track: opt-in real-CLI contract job in CI, history secrets scan, PyPI publish (GO-gated).
