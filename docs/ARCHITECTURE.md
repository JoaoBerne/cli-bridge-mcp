# Architecture

A map of how cli-bridge is built, so you can find your way around and change it safely.

## Mental model

cli-bridge is an **MCP server**. Your AI host (Claude Code, Codex, …) connects to it over stdio.
The server exposes tools (`ask_gemini`, `ask_all`, `review_diff`, …). When the host calls one,
the server **spawns the matching official CLI as a subprocess**, captures its output, cleans it,
and hands it back. It never stores tokens or API keys.

```
host (Claude/Codex/…) ──MCP/stdio──▶ cli-bridge ──spawn subprocess──▶ official CLI ──▶ model
                                          │
                                          ├─ keeps the host's own lane out of fan-out
                                          ├─ kills the whole process tree on timeout/cancel
                                          ├─ redacts secrets, classifies errors
                                          └─ spills huge output to a file (keeps host context lean)
```

## Module map (`src/cli_bridge/`)

| File | Responsibility | Rule of thumb |
|------|----------------|---------------|
| `server.py` | The MCP surface: list tools, dispatch `call_tool`, the hot path `_run_lane` (model/cwd resolution, spend gates, cache, preamble, spawn, telemetry), `_emit`, and `_run_workflow_preset` — the table that maps a `workflow` preset name to its `orchestrate` / `workflows` function. | Route and glue only. |
| `mcp_compat.py` | The `mcp` 1.x/2.x seam: binds the handlers to whichever major is installed and re-implements the envelope 1.x gave for free (input validation, `isError` on a raise). | **The only file that may branch on the SDK version.** |
| `schemas.py` | Tool-schema assembly: `_tools_for`, `_ask_schema`, the shared `_P` parameter dict, `DEFAULT_TOOLS` and `_filter_tools` (the `CLI_BRIDGE_TOOLS` knob). Pure. | A new tool = a `Tool(...)` here + a dispatch branch in `server.py`. |
| `reports.py` | `doctor` / `doctor_deep`, the markdown renderers and the `setup` recommendation. Pure, couplings injected. | — |
| `prompts.py` | MCP prompt builders (`apilookup`). | — |
| `resources.py` | MCP resource payloads: `cli-bridge://config`, `://lane-stats`, `://usage-summary`. | — |
| `lanes.py` | The lane registry: one `LaneSpec` per CLI + argv builders + the custom-lane JSON loader (`CLI_BRIDGE_LANES_FILE`), PATH detection (`is_installed`, `installed_lanes`), model probes for opencode/ollama, `availability_env` gating. | Add a CLI = add a `LaneSpec`. Never touch the server. |
| `bridges/` | `openai_compatible.py` = the `cli-bridge-openai` console script (`urllib` only). The runner spawns it like any lane; the API key comes from the env var named in `--key-env` (optional — keyless for local servers). Used by the `applepcc` lane and custom HTTP lanes. | No new dependency. |
| `runner.py` | Runs a subprocess safely: timeout, process-tree kill, secret redaction, ANSI cleanup, error classification (`quota`/`auth`/`timeout`/`empty`/`policy`/…), output cap, per-lane pacing, optional streaming. Returns a `RunResult`. | All "how do we spawn safely" lives here. |
| `config.py` | Env parsing (`lane_env*` helpers for `CLI_BRIDGE_<LANE>_*`), cost profile, timeouts, the config-file loader, the server `INSTRUCTIONS`. | Need a new env var? It goes here. |
| `telemetry.py` | Local sqlite: run log, per-lane health/cooldown, response cache, job rows, ratings + lessons, estimated tokens/credits. | **Best-effort: must never raise into a delegation.** |
| `router.py` | Pure ordering for `ask_cascade` (cheapest→strongest) and `ask_best` (per `mode`, weighted by `rate_lane` scores), skipping cooled lanes. | No side effects. |
| `council.py` | The fan-out: `ask_all` (+ agreement score) / `ask_cascade` / `ask_best` / `synthesize` + the council recap. | Injected `run_lane`, testable with fakes. |
| `workflows.py` | `review_diff` (both focuses), `debate` (judge and borda votes), `premortem`, `test_plan`, `challenge`, `git_text`, the deterministic prechecks. | Injected `run_lane`. |
| `orchestrate.py` | Durable fan-out (`batch_run`: journaled in sqlite, `resume_id`, per-invocation `max_calls`/`max_credits`, `dry_run` envelope) + the presets `refine_plan`, `map_review`, `research_verify`, `fanout_compare`, `converge`. | Presets are hardcoded steps, not a DSL. |
| `findings.py` | Pure: parse each reviewer's JSON tolerantly, merge by file/line/title, derive confidence from agreement, render markdown or JSON. | Deterministic merge — can't fabricate findings. |
| `jobs.py` | In-process async jobs: wrap a coroutine in a task, return a job id, poll/fetch/cancel/list. Results spill to a file; sqlite row is best-effort. | No cross-restart resume — stale `running` rows become `interrupted`. |
| `buildloop.py` | Steerable multi-turn direct builds: progress log (`job action=tail`), steer/interrupt via an asyncio.Event, executable Definition-of-Done (`dod_cmd`), bounded by `max_turns` / `max_fail_retries`. | A 0-file turn warns (plan-leak). |
| `worktrees.py` | `ask_build`: `mode=isolated` → throwaway worktree → diff (+ `apply`); `mode=direct` → zone contract (in-process `asyncio.Lock` per (repo, zone), post-turn out-of-zone detection, zone-scoped revert, artifacts by path). | The real repo is only ever touched inside the zone. |
| `conversations.py` | Round-table threads: sqlite transcript, recipient-aware replay, rolling summary, auto-threading. | Replay is the source of truth for every lane. |
| `guards.py` | Scans untrusted delegate output for prompt-injection / tool-poisoning; `CLI_BRIDGE_GUARD=off\|warn\|strict`. | Runs in `_emit` after redaction. |
| `preamble.py` | The terse response-style preamble prepended to delegate prompts. | Prose only — never on structured (JSON) workflows. |
| `cli.py` | Human/CI entry point (`cli-bridge …`) over the same internals. | Thin wrappers. |

Outside the package: `tests/` (no real CLI or network), `benchmarks/` (the council-vs-single eval
harness, `PYTHONPATH=src python benchmarks/eval.py`), `examples/` (lane JSON recipes),
`plugin/` (the Claude Code plugin manifest).

## Request lifecycle (one `ask_<lane>` call)

1. **`list_tools`** — which lanes are installed, one `ask_<lane>` each (the host's own lane is a
   normal tool but never joins fan-out), plus the fixed tools filtered by `CLI_BRIDGE_TOOLS`.
2. **`call_tool`** dispatches by name.
3. **`_run_lane`**: resolves model, agent mode (plan/build), effort, cwd (caller's `cwd` >
   `CLI_BRIDGE_DEFAULT_CWD` > first usable MCP root > launch dir); applies the two spend gates
   (`CLI_BRIDGE_<LANE>_DAILY_LIMIT`, `CLI_BRIDGE_DAILY_CREDIT_CAP`); checks the response cache;
   prepends the terse preamble; builds argv and calls **`runner.arun`**; records telemetry.
4. **`runner.arun`** spawns, enforces the timeout (killing the process group), redacts,
   classifies, caps → `RunResult`. A streamed run that times out keeps what already streamed.
5. **`_emit`** runs the output guard, then returns inline if small or spills to a file and
   returns a preview + path.

## Design invariants

1. **Ban-safe**: only ever spawn official CLIs. No token extraction, no API keys by default.
2. **No pollution of the user's CLI setup**: the only writes are the overflow dir, the telemetry
   sqlite, the config file (`set_lane_cost`) and an optional log (`test_isolation.py`).
3. **Cost safety**: an empty model never resolves to a paid one; `ask_all` / `ask_cascade` /
   `ask_best` exclude limited/paid lanes by default; `saver` refuses `include_paid`.
4. **Read-only by default**: writes need `agent=build` or `ask_build`; isolated mode confines
   them to a worktree. `CLI_BRIDGE_VERIFY_PLAN_READONLY=1` flags (never reverts) a plan-mode
   delegate that wrote anyway.
5. **Telemetry never raises** into a delegation path.
6. **Portable**: macOS/Linux/Windows (`runner._kill_tree` has a Windows branch).
7. **Stdlib + `mcp` only.**
8. **Re-entry capped**: every spawn carries `CLI_BRIDGE_DEPTH`; `_run_lane` refuses past
   `CLI_BRIDGE_MAX_DEPTH` (default 1).
9. **Both `mcp` majors work**, every version branch confined to `mcp_compat.py`; CI runs the
   suite on both.

## Extending it

- **Add a CLI**: a `LaneSpec` in `lanes.py`, or a JSON entry via `CLI_BRIDGE_LANES_FILE`
  (see `examples/`). Wrap an OpenAI-compatible HTTP API with `curl` or `cli-bridge-openai`;
  `availability_env` keeps the lane hidden until its key is exported.
- **Add a workflow preset**: a function in `workflows.py` or `orchestrate.py` taking the
  injected `run_lane`, one row in `_run_workflow_preset`, the name in the `preset` enum in
  `schemas.py`.
- **Every change ships a test** that needs no real CLI or network (fake lanes via `echo`,
  temp sqlite via `CLI_BRIDGE_STATE_DB`).

See `CHANGELOG.md` for history and `AGENTS.md` for contributor rules.
