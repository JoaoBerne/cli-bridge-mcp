# Architecture

A map of how cli-bridge is built, so you can find your way around and change it safely.

## One-paragraph mental model

cli-bridge is an **MCP server**. Your AI host (Claude Code, Codex, …) connects to it over
stdio. The server exposes **tools** (`ask_gemini`, `ask_all`, `review_diff`, …). When the host
calls a tool, the server **spawns the matching official CLI as a subprocess**, captures its
output, cleans it, and hands it back. It never stores your tokens or API keys — it runs the same
binaries you run by hand. That's the whole trick.

```
host (Claude/Codex/…) ──MCP/stdio──▶ cli-bridge ──spawn subprocess──▶ official CLI ──▶ model
                                          │
                                          ├─ keeps the host's own lane out of fan-out (CLI_BRIDGE_HIDE_HOST=1 hides it)
                                          ├─ kills the whole process tree on timeout/cancel
                                          ├─ redacts secrets, classifies errors
                                          └─ spills huge output to a file (keeps host context lean)
```

## Module map (`src/cli_bridge/`)

| File | Responsibility | Rule of thumb |
|------|----------------|---------------|
| `server.py` | The MCP surface: list tools, dispatch calls, list/serve prompts. Thin glue. | **No business logic here** — it should only route. |
| `lanes.py` | The **lane registry**: one `LaneSpec` per CLI (claude/gpt/gemini/mistral/opencode/qwen/copilot) + the argv builders (`_claude_ask`, …) + the custom-lane JSON loader. | Add a CLI = add a `LaneSpec`. Never touch the server. |
| `runner.py` | Runs a subprocess safely: timeout, process-tree kill, secret redaction, error classification (`quota`/`auth`/`timeout`/…), output cap. Returns a `RunResult`. | All "how do we spawn safely" lives here. |
| `config.py` | All env parsing, timeouts, cost profile, onboarding text. **Single source of truth** for settings. | Need a new env var? It goes here. |
| `telemetry.py` | Local sqlite: run log + per-lane health/cooldown + response cache + async-job rows + estimated token/credit accounting. | **Best-effort: must never raise into a delegation.** |
| `router.py` | Pure functions that order lanes for `ask_cascade` (cheapest→strongest) and `ask_best` (per-mode: fast/cheap/deep/code/review/security), skipping cooled ones. | No side effects — pure, easy to test. |
| `council.py` | The fan-out itself: `ask_all` (+ `agreement` score) / `ask_cascade` (opt-in confidence-escalate) / `ask_best` / `synthesize` + the `council_recap` digest. Extracted from `server.py`; takes injected `run_lane` / `emit` / `progress` / `host_sample`. | Same injection pattern as `workflows.py` — testable with fakes. |
| `workflows.py` | The multi-model workflows: `review_diff`, `security_review`, `debate` + the `council_recap` digest + deterministic `prechecks` (secrets / dangerous shell). Orchestrates several lanes. | Takes an injected `run_lane`, so it's testable with fakes. |
| `orchestrate.py` | Durable fan-out (`batch_run`: typed result + provenance, per-invocation budget caps + `dry_run` cost envelope, SQLite-journalled `resume_id`) + presets: `refine_plan`, `council_review`, `map_review`, `research_verify`, `verify_repair`, `fanout_compare`, **`jury`** (cross-vendor, author≠reviewer, k-of-N fail-closed). | Presets are hardcoded post-fan-out steps, not a DSL — the host composes logic. |
| `findings.py` | Pure: parse each reviewer's JSON tolerantly, merge by file/line/title, derive confidence from agreement, render Markdown or a JSON result. | No I/O — deterministic merge replaces an LLM merge pass (can't fabricate findings). |
| `jobs.py` | In-process async jobs (`ask_all_async`): wrap a coroutine in `asyncio.create_task`, return a job id, poll/fetch/cancel later. Live registry + best-effort sqlite row. | No cross-restart resume in v1 — stale `running` rows become `interrupted`. |
| `preamble.py` | The terse response-style preamble prepended to delegate prompts. | Prose only — never applied to structured (JSON) workflows. |
| `guards.py` | Scans UNTRUSTED delegate output for prompt-injection / tool-poisoning; `CLI_BRIDGE_GUARD=off\|warn\|strict`. | Runs in `_emit` after redaction; never on cli-bridge's own reports. |
| `worktrees.py` | `ask_build`: `mode=isolated` runs a build agent in a throwaway worktree → diff (repo untouched); `mode=direct` writes real files under a git **zone contract** (per-zone lock, post-turn out-of-zone-write detection + zone-scoped revert) and returns non-text files as **artifacts by path**. | Real repo only ever touched inside the zone; undo is never a global reset. |
| `buildloop.py` | Steerable multi-turn builds: `job_tail` / `build_steer` / interrupt, an executable Definition-of-Done gate (`dod_cmd`), filesystem continuity (no transcript). | Bounded by `max_turns` / `max_fail_retries`; a 0-file turn warns (plan-leak). |
| `detect.py` | Which CLIs are actually installed (PATH lookup). | — |
| `cli.py` | Human/CI entry point (`cli-bridge …`) over the SAME internal functions the MCP tools use. | Thin wrappers — no logic of its own. |

## Request lifecycle (a single `ask_<lane>` call)

1. **`list_tools`** (`server.py`) — figures out which lanes are installed, hides the caller's own
   lane, and returns one `ask_<lane>` tool per remaining lane (+ `ask_all`, `doctor`, workflows…).
2. The host calls a tool → **`call_tool`** dispatches by name.
3. **`_run_lane`** (the heart):
   - resolves the model (`lane.model_for`), the agent mode (plan/build), the effort, the cwd;
   - checks the **response cache** (if enabled) → return early on a hit;
   - prepends the **terse preamble** (unless this is a structured workflow);
   - builds the argv (`lane.build_ask(...)`) and calls **`runner.arun`**;
   - records **telemetry** (duration, status, kind) and stores the cache entry on success.
4. **`runner.arun`** spawns the CLI, enforces the timeout (killing the whole process group on
   expiry/cancel), redacts secrets, classifies the exit, caps the size → `RunResult`.
5. **`_emit`** (`server.py`) runs the **output guard** over untrusted delegate text (warn/strict
   per `CLI_BRIDGE_GUARD`), then returns the answer inline if small, or spills it to a file and
   returns a preview + path if huge (so the host's context stays lean).

## Tool catalog

- **`ask_<lane>`** — one model. Params: `task`, `model`, `effort`, `agent` (plan|build), `cwd`,
  `timeout_s`. `agent: build` lets it **edit files**.
- **`ask_build_isolated`** — the SAFE way to use write mode: runs a build-capable lane in a
  throwaway git worktree at HEAD and returns the diff; your real repo is never touched.
- **`ask_all`** — same question to every free, non-limited lane in parallel; `synthesize: true`
  adds an agree/disagree summary. For **comparing** opinions. Output opens with a one-line-per-
  lane **council recap** so no answer is a blind spot.
- **`ask_all_async` / `job_status` / `job_result` / `job_cancel` / `jobs_list`** — the same
  fan-out as a background job that returns a job id in <1s, so a slow run can't hit the host's
  tool-call deadline. Cancel kills the delegates' process groups; a restart marks it interrupted.
- **`ask_cascade`** — one answer with automatic fallback (cheapest→strongest, skips cooled lanes).
  For **reliability/automation**, not comparison.
- **`ask_best`** — picks ONE lane by `mode` (fast/cheap/deep/code/review/security) from cost,
  health and measured latency, then runs it with fallback. For "just use the right model".
- **`route_plan`** — explains the order cascade would try (runs nothing); `mode` previews `ask_best`.
- **`usage_report` / `usage_budget`** — local stats with ESTIMATED tokens (chars/4) and credits
  (per-lane `CREDITS_PER_1K`); budget shows today's runs vs `DAILY_LIMIT`. Always labelled estimated.
- **`review_diff` / `security_review`** — role-diverse multi-model review of a git diff. Each
  reviewer returns JSON findings; deterministic prechecks (secrets, dangerous shell) seed the
  set; findings merge by file/line/title with agreement-based confidence (single/majority/
  consensus). `output_format: markdown` (default, PR-friendly) or `json`. `security_review`
  adds a `residual_risk` section.
- **`debate`** — models answer, see each other, revise over bounded rounds, a judge concludes.
- **`premortem`** — each lane imagines the plan failed → merged, prioritized risk list (run before building).
- **`test_plan`** — test plan (behaviors, edge cases, concrete cases) from a git diff or a description.
- **`doctor`** — health check (installed CLIs, host, cost profile, cooldowns). `deep: true` live-probes auth.
- **`lane_stats` / `reset_lane_state`** — per-lane health + cooldown management.
- **`setup`** — walk the user through the cost profile.
- **Self-model**: from a given host, `ask_<host>` appears as a separate tool that **requires an
  explicit model** — so you can consult a sibling model of your own family.
- **MCP prompts**: `review_diff`, `security_review`, `debate`, `premortem`, `test_plan`,
  `cost_setup` show up as native slash commands in hosts that support prompts.
- **MCP resources**: `cli-bridge://config`, `://lane-stats`, `://usage-summary`,
  `://workflow-schemas/review-diff` — read-only JSON snapshots of cli-bridge's own state.
- **Human CLI**: `cli-bridge doctor|ask|ask-all|ask-best|review-diff|security-review|test-plan|
  premortem|stats|usage|budget|jobs|setup` — same engine, terminal/CI friendly (`--json`).

## Design invariants (don't break these)

1. **Ban-safe**: only ever spawn official CLIs. No token extraction, no API keys.
2. **No pollution of the user's CLI setup**: the only writes are an overflow temp file, the
   telemetry sqlite, and an optional log. Never to `~/.gemini`, `~/.codex`, etc. (Test:
   `test_isolation.py`.)
3. **Cost safety**: an empty/missing model must never resolve to a paid model; `ask_all` /
   `ask_cascade` exclude limited/paid lanes by default.
4. **Read-only by default**: writes happen only with explicit `agent: build`, annotated
   destructive — and `ask_build_isolated` confines them to a throwaway worktree.
5. **Telemetry never raises** into a delegation path.
6. **Portable**: macOS/Linux/Windows (see `runner._kill_tree`'s Windows branch).
7. **Stdlib + `mcp` only**: no new runtime dependencies.
8. **Re-entry capped**: every spawn carries `CLI_BRIDGE_DEPTH`; `_run_lane` refuses past
   `CLI_BRIDGE_MAX_DEPTH` (default 1) so a delegate can't recurse into the bridge.

## Extending it

- **Add a CLI**: append a `LaneSpec` in `lanes.py`, or — without forking — point
  `CLI_BRIDGE_LANES_FILE` at a JSON file. Wrap any HTTP API by spawning `curl`.
- **Add a workflow**: add a function in `workflows.py` taking `(targets, args, run_lane)`, then
  register a tool + dispatch in `server.py`.
- **Every change ships a test.** Tests must not need a real CLI or network (fake lanes via
  `echo`, temp sqlite via `CLI_BRIDGE_STATE_DB`).

## Positioning & horizon (honest framing)

What cli-bridge **is, today**: the best dev tool for driving the several AI CLIs you already pay
for, and orchestrating sub-agents across them — fan-out, cost-tiered cascade, cross-model review,
guarded real builds, durable workflows. That is real and shipped.

What it is **not** (yet, and maybe never): a universal "protocol between AIs." The longer-horizon
idea — a neutral bus where agents from different vendors collaborate — is a *direction*, not a
product claim. It rests entirely on the CLIs staying scriptable, which the vendors control and
could change; "ban-safe" means "no token/key extraction", not a guarantee. So the big-architecture
items (recursive spawn trees, a shared state bus, inter-agent mailboxes, a capability-passthrough
hub, a typed wire-protocol) live on the roadmap, gated on real demand and on the substrate holding
— never sold as if they ship. We build for the real thing now and are upfront about the rest.

See `CHANGELOG.md` for the shipped history and `AGENTS.md` for contributor rules.
