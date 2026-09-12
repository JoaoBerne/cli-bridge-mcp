# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims for
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.3.0 — 2026-09-12

0.2.0 was never tagged or published: everything since 0.1.5 ships here.

- Requires Python 3.12+ (was 3.10; 3.10 reaches end of life in October 2026). CI runs 3.12, 3.13 and 3.14.
- Marketing copy removed: banner, badges wall, `docs/COMPARISON.md`, and the MCP instructions text is now a plain tool list.

"Too much stuff, nobody can follow it." The MCP surface shrinks from ~37 tool names to 15 fixed
tools + `ask_<lane>`, and the ring of things bolted on around the core is gone. Nothing you
could do before is lost: every removed tool folds into a parameter of one that stays.
**Hosts cache tool names — restart your MCP host after upgrading.**

### BREAKING — tools

| Removed | Use instead |
|---|---|
| `ask_all_async` | `ask_all(async=true)` |
| `ask_build_isolated` | `ask_build` (`mode=isolated` is the default) |
| `route_plan` | `ask_cascade(dry_run=true)` / `ask_best(mode=…, dry_run=true)` |
| `job_status` / `job_result` / `job_cancel` / `jobs_list` / `job_tail` / `build_steer` | `job(action=status\|result\|cancel\|list\|tail\|steer, job_id=…)` |
| `consensus` | `debate(vote=borda)` (`synthesize=true` for the chairman blend) |
| `challenge` / `premortem` / `test_plan` | `workflow(preset=challenge\|premortem\|test_plan)` |
| `commit_msg` / `pr_describe` | `git_text(kind=commit\|pr)` |
| `conversations_list` / `conversation_show` | `conversations()` / `conversations(id=…)` |
| `security_review` | `review_diff(focus=security)` |
| `list_<lane>_models` | `list_models(lane=…)` |
| `usage_report` / `lane_stats` | MCP resources `cli-bridge://usage-summary`, `cli-bridge://lane-stats` (and `cli-bridge usage` / `cli-bridge stats`) |
| `usage_budget` | gone — `doctor` shows per-lane runs today against `DAILY_LIMIT` |
| `batch_run` / `reset_lane_state` | still registered, hidden by default: `CLI_BRIDGE_TOOLS=all` or `CLI_BRIDGE_TOOLS=default,batch_run` |

Also dropped: the MCP prompts `review_diff` / `security_review` / `debate` / `cost_setup` /
`premortem` / `test_plan` (`apilookup` stays), the resource `cli-bridge://workflow-schemas/review-diff`,
and `ask_cascade(escalate=)` (confidence-escalate). Telemetry `tool=` labels in sqlite are unchanged.

### BREAKING — presets, env, CLI, files

- **Workflow presets removed**: `jury`, `verify_repair`, `council_review`. `converge` covers the
  first two (`verifiers=N max_rounds=1` for a vote, `max_rounds=N` for a repair loop);
  `fanout_compare` takes `council_review`'s arguments. Enum now: `refine_plan`, `map_review`,
  `research_verify`, `fanout_compare`, `converge`, `premortem`, `test_plan`, `challenge`.
- **Env vars no longer read** (harmless if still set): `CLI_BRIDGE_LEAN`, `CLI_BRIDGE_ENABLED_TOOLS`,
  `CLI_BRIDGE_DISABLED_TOOLS` (all → the one `CLI_BRIDGE_TOOLS` knob), `CLI_BRIDGE_HIDE_HOST`
  (the host's own `ask_<lane>` is always a normal tool, never in fan-out), `CLI_BRIDGE_ECHO_TASK`
  (the "▶ lane — asked:" header is gone), `CLI_BRIDGE_NATIVE_SESSIONS`, `CLI_BRIDGE_CONVO_LOG_DIR`.
- **CLI subcommands removed**: `init` (use `claude mcp add cli-bridge -- uvx cli-bridge-mcp` or
  the JSON snippet in the README), `setup --write` (the env template is in the README),
  `bench`, `eval` (moved, below), `usage-budget`/`budget`.
- **Lane removed**: the built-in `openrouter` API lane and `examples/byo-api-lane.json`. The
  `cli-bridge-openai` bridge stays (the `applepcc` lane and local HTTP runtimes spawn it).
- **Files removed**: `docs/i18n/` (6 translations), `site/` + `.github/workflows/pages.yml`,
  `docs/BENCHMARKS.md`, `docs/demo/`, `assets/demo-borrow.gif`, `plugin/skills/` (the five
  `/cli-bridge:*` slash commands; the plugin still wires the MCP server), `smithery.yaml`,
  `examples/github-action-pr-review.yml`, `examples/native-session.lane.json`,
  `tests/test_live_e2e.py`. `examples/llamacpp|lmstudio|mlx.lane.json` → one
  `examples/local-runtime.lane.json` (+ a runtime table in `examples/local-first-host.md`).
- **Eval harness moved out of the package**: `src/cli_bridge/eval.py` → `benchmarks/eval.py`
  (`PYTHONPATH=src python benchmarks/eval.py`, the former `cli-bridge eval`), scorer tests →
  `benchmarks/tests/`, corpus → `benchmarks/fixtures/evalset/`. Not in `pytest` testpaths, not
  in the sdist.
- **Modules removed**: `budget.py` (the two spend gates are inlined at the top of
  `server._run_lane`), `detect.py` (`is_installed` / `installed_lanes` moved into `lanes.py`),
  `consensus_loop.py` (folded into `orchestrate.converge` as locals).
- **Internals removed**: native-session continuity (`--session-id`/`--resume` splice,
  `convo_sessions` table, `LaneSpec.native_session`), the conversation `.md` log mirror, jury
  tables and `seat_report`, `verify_repair`, `files_required` / `allow_ungrounded`, the
  `fact_check` / `steelman` passes, `brief_lint`, the convergence label and `residual_risk`
  section, the flag-drift probe (`probe_flags`, `lanes.missing_flags`), the cross-process zone
  lock (now an in-process `asyncio.Lock` per repo+zone — two servers on one repo no longer
  serialise), the `role` / `task_hash` columns of `runs`.

### Fixed
- **A streamed run that times out keeps what already streamed** instead of throwing it away.
- **`rate_lane` notes are surfaced as "Past lessons"** in `ask_best` output (they were stored
  but never read back).
- Native-session fixes (retry collision on a fresh `--session-id`, a high-water mark that
  claimed undelivered turns, a ghost session under `CLI_BRIDGE_MOCK`, a splice that assumed the
  prompt was last) landed and were then superseded by the removal of native sessions above.
- **One ordinary failure no longer un-benches a cooled lane**: `lane_state` carried a
  `cooldown_until` blank on any `kind="failed"` run; the bench now carries forward, success
  still clears it. `consecutive_failures` counts every consecutive failure.
- **`cli-bridge-openai` sends `stream: false` explicitly** (Apple's `fm serve` streams SSE
  unless told otherwise, and the bridge parses one JSON object).
- **drift-check names the right culprit**: `import cli_bridge.server` is checked separately from
  the test run; dedup is by issue title; the newest `mcp` is probed in a throwaway venv
  (informational).

### Added
- **Runs on `mcp` 2.x as well as 1.x** — dependency `mcp>=1.2.0,<3`. 2.0.0 removed the six
  low-level decorators, moved the request context onto the handler and renamed model attributes
  to snake_case; all of that lives in **`mcp_compat.py`**, which also re-implements input
  validation and `isError`-on-raise. CI runs the suite on both majors.
- **`CLI_BRIDGE_DEFAULT_CWD`** — pin the directory delegates run in when the caller names no `cwd`.
- **Apple Foundation Models**: `ask_apple` spawns `fm` for on-device inference ($0, offline,
  unmetered, read-only by construction); `ask_applepcc` (hidden until `APPLE_FM_SERVE_URL`) is
  an HTTP client to a `fm serve` you start yourself — PCC gates on session attribution, so it
  refuses any process cli-bridge spawns. Recipe: `examples/apple-fm-serve.lane.json`.
- **Vision on five lanes**: `images=[…]` is lane data (`LaneSpec.image_arg`) — an argv flag
  (`apple --image`, `gpt -i`, `opencode -f`) or a prompt prefix (`gemini @`, `ollama` bare).

### Changed
- **A delegate with no `cwd` runs in the host's workspace** (first MCP root), not wherever the
  server was launched. Precedence: caller's `cwd` > `CLI_BRIDGE_DEFAULT_CWD` > first usable MCP
  root > inherited cwd. This narrows where an unscoped `build` delegate can write.
- **`cli-bridge-openai --key-env` is optional** — omit it for a keyless local server; naming an
  empty env var still fails with `missing-auth`.
- A shared `_P` parameter dict in `schemas.py` replaces ~90 per-tool re-declarations (shapes
  byte-identical).

Tests: 735 → 682 passed (53 covered only deleted behaviour), ruff and mypy clean.

## [0.1.4] - 2026-06-13

### Added
- **Read-only mutation guard (`CLI_BRIDGE_VERIFY_PLAN_READONLY`, opt-in).** A `plan` delegate
  that writes files in a git repo gets a `⚠️ WORKSPACE MUTATION DETECTED` warning and
  `RunResult.mutated`. Never auto-reverts.
- **Opt-in API lanes (`availability_env`) + `cli-bridge-openai`.** A lane declaring
  `availability_env` stays hidden until that env var is set. The bridge is `urllib`-only, reads
  the key from the named env var (never argv), POSTs to `/chat/completions`; `--list-models`.
  BYO pattern in `examples/openai-compatible.lane.json`. (Also shipped a built-in `ask_openrouter`
  lane, removed in 0.3.0.)
- **`workflow preset=converge`** — author drafts; an independent arbiter commits a blind verdict
  before seeing peers; anonymized cross-family peers review; the arbiter adjudicates every issue
  with a reason; revise-or-converge bounded by `max_rounds` (default 5, cap 6). Converges only if
  ≥1 peer responds, all approve, none reject, zero accepted blockers, and the blind verdict was
  APPROVE.
- **Issue-category taxonomy on findings**: `{security, correctness, scope, ambiguity,
  performance, ops}`, orthogonal to severity; null when unrecognised.
- **MCP registry manifest**: `server.json` on the `2025-12-11` schema + the `mcp-name` marker in
  the README.
- **Auto-threaded asks**: an `ask_<lane>` with no `conversation` records its exchange under a
  fresh thread id and returns it. `CLI_BRIDGE_CONVO_AUTOTHREAD=off` restores stateless asks.
- **`docs/HOSTS.md`** — per-host MCP config locations + a rules snippet for proactive use.

### Changed
- **`server.py` split** (2,589 → ~1,110 lines): schemas → `schemas.py`, reports/doctor →
  `reports.py`, prompts → `prompts.py`, resources → `resources.py`; symbols re-exported, surface
  byte-identical.
- Landing page and README hero reworked (pain-first); server `instructions` wording ("a second
  opinion before shipping something risky or hard to reverse").
- **License: MIT → Apache 2.0** (+ `NOTICE`).

## [0.1.3] - 2026-06-12

### Added
- Custom lanes can declare `native_session` in JSON (removed in 0.3.0).
- **Native session continuity** on round-table turns for claude (`--session-id`/`--resume`)
  and opencode (`--print-logs` capture, `-s` resume), prompt carries only the delta; replay
  stays the source of truth. `CLI_BRIDGE_NATIVE_SESSIONS=off`. (Removed in 0.3.0.)
- **Rolling summary on round-table threads**: past `CLI_BRIDGE_CONVO_MAX_CHARS`, the answering
  lane condenses the oldest turns into one `summary` turn. `CLI_BRIDGE_CONVO_SUMMARY=off`.
- **`ask_build apply=true`** (isolated): lands the diff as unstaged changes, `git apply --check`
  first (all-or-nothing). Also `cli-bridge build --apply`.
- **`ask_build lane` optional**: empty = first free build-capable lane in router order.

### Fixed
- Full multi-model review pass: the latest exchange always survives compaction; buildloop
  fingerprint only stats porcelain-listed paths; interrupted telemetry writes roll back; a
  `zone` escaping `target_dir` is rejected; vibe read-only asks use the `default` agent.
- **ANSI escape cleanup** in both runner paths (CSI, OSC, charset sequences).
- **`challenge` falls back across lanes** when no `lane` is named.
- Steerable builds: content edits of already-untracked files no longer trigger a false
  "changed 0 files" warning (zone fingerprint mtime+size).
- `fanout_compare` `lane:model` examples use the full model id (`opencode:opencode/mimo-v2.5-free`).

### Changed
- `ask_build` description leads with WHEN to delegate.

## [0.1.2] - 2026-06-11

### Added
- **Roles v2**: built-ins grow to 7 (`architect`, `oracle`, `simplifier` added; cap 8);
  `CLI_BRIDGE_ROLES_FILE` (JSON `{"name": "persona"}`) extends them; `role=` also accepts an
  inline persona. `doctor` reports the file's load status.
- **Desktop-app hosts**: CLI detection falls back to the common install dirs (`~/.local/bin`,
  `~/.npm-global/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, …).
- **Question echo** (`CLI_BRIDGE_ECHO_TASK`) on delegation results (removed in 0.3.0).
- **Claude Code plugin** (in-repo marketplace) wiring the MCP server + five skills (skills
  removed in 0.3.0).

### Changed (budget coherence)
- **`CLI_BRIDGE_<LANE>_DAILY_LIMIT` is ENFORCED at spawn** (it was only reported before).
- **The daily credit cap gates any credit-spending lane**, not just `paid` (a `limited` lane
  with `CREDITS_PER_1K` spends credits).
- Both gates fail open if local telemetry is unavailable.
- `doctor` annotates each tier's source (`default` / `set by you: config file` / `set by you:
  host env`), shows enforced daily limits with today's count, flags a user-set `cost=free`
  that predates a vendor sunset.
- **`docs/BUDGET.md`** — the whole cost model on one page.

## [0.1.1] - 2026-06-11

### Changed (cost truth)
- **`saver` is enforced**: `include_paid=true` is refused (`config.include_paid_resolved`, shared
  by `ask_all`/`ask_cascade`/`ask_best`).
- **mistral default `free` → `limited`**; override with `set_lane_cost` / `CLI_BRIDGE_MISTRAL_COST=free`.
- **Vendor sunsets are date-gated** (`LaneSpec.sunset`): a `free` default degrades to `limited`,
  bin resolution prefers the successor. Applied to gemini (free tier ends **2026-06-18**,
  successor `agy`).
- `doctor` warns when `CLI_BRIDGE_DAILY_CREDIT_CAP` is unenforceable (paid lane without
  `CREDITS_PER_1K`); `set_lane_cost` warns when a host env var will shadow the persisted value;
  hyphenated lane keys round-trip (`-` → `_`).
- First-run nudge keys on `cost_config_is_set()` (profile OR per-lane costs).
- `ask_all` schema stops advertising 900 s while clamping to 60 s.

### Added
- **`cli-bridge set-cost <lane> <free|limited|paid> --note '…'`**.
- **`lane:model` entries in `workflow preset=fanout_compare`** — several models of one lane side by side.

### Fixed (docs)
- Vendor facts re-verified (Codex ~1M context, Grok 1M / CLI 256k, Gemini Nano Banana needs its
  own key, Cerebras free context 65k/64k, `doctor --deep`); gpt-image-2 = real text-to-image in
  Codex CLI on paid plans; the 30-tool reference moved to `docs/TOOLS.md`.

## [0.1.0] - 2026-06-08

First public release on PyPI (`pip install cli-bridge-mcp`).

### Added (local lane, council quality, quota resilience)
- **`cli-bridge build <lane> "<task>"`** (human CLI): throwaway worktree → diff; `--architect <lane>`.
- **Ollama lane** (`ask_ollama`): `run --hidethinking <model>`, $0, offline, read-only; empty
  model = first from `ollama list`.
- **Local-model recipes** in `examples/`.
- **Peer-anonymized debate/council** (neutral `Reviewer A/B` / `Debater 1/2` labels).
- `seat_report` / `jury_outcomes` telemetry (removed in 0.3.0).
- **Quota-empty cooldown with capped backoff**: after `COOLDOWN_EMPTY_THRESHOLD` consecutive
  empties, each further empty doubles the wait, capped at `COOLDOWN_EMPTY_MAX_S` (6 h); a
  success resets to the 30-min base.
- Eval calibration bins on the discrete emitted confidences, N≥50 gate.

### Added (orchestration engine)
- `workflow preset=jury` — cross-family k-of-N vote, fail-closed, `lanes.family_of` +
  `CLI_BRIDGE_FAMILY_OVERRIDES` (preset removed in 0.3.0; `family_of` stays for `converge`).
- **Typed result envelope + provenance** on `batch_run` (model / kind / latency_ms / exit_code);
  `findings.extract_json(text) -> (value, error)`.
- **Per-invocation budget**: `batch_run max_calls` / `max_credits` (over-budget tasks skipped,
  not journalled) + `dry_run` cost envelope.
- **`ask_all` `agreement` score** (0–1, mean pairwise difflib ratio).
- `ask_cascade escalate=true` confidence-escalate (removed in 0.3.0).
- **`role=` personas** on `ask_<lane>`; **`ask_gemini images=[…]`** (experimental).
- `verify_repair cross_family=true` (preset removed in 0.3.0).

### Safety / fixes
- **`CLI_BRIDGE_DEPTH` re-entry guard**: a delegate at/over `CLI_BRIDGE_MAX_DEPTH` (default 1) is refused.
- `batch_run` per-task `timeout_s` is threaded through.

### Changed (surface)
- `CLI_BRIDGE_LEAN=1` curated core-12 surface (replaced by `CLI_BRIDGE_TOOLS` in 0.3.0).
  `usage_report format` → `output_format`.
- **Host's own lane visible by default** as a normal tool, still kept out of fan-out
  (`CLI_BRIDGE_HIDE_HOST=1` to hide; removed in 0.3.0).

### Added (cross-CLI orchestration)
- **Artifact return** (`ask_build mode=direct`): non-text files the build writes are reported
  by path (type + size) instead of a "Binary files differ" diff.
- `workflow preset=verify_repair` (removed in 0.3.0) and **`fanout_compare`** (same task to N
  lanes side by side, optional `judge_lane`).

### Changed (internal)
- **`council.py` extracted** from `server.py` (injected `run_lane`/`emit`/`progress`/`host_sample`).
- **mypy gate in CI** (typed `_ann()` helper for the SDK-stub noise).
- **eval v3**: seeded permutation test over per-fixture recall; corpus 22 fixtures / 22 bugs
  with decoys inside buggy fixtures.

### Added (supervised delegation)
- **`ask_build`** — `mode=isolated` (default, worktree diff; `ask_build_isolated` became an
  alias) and `mode=direct`: writes only inside `zone`, zone-scoped undo, per-zone lock, a
  post-turn `git status -uall` vs snapshot catches any write outside the zone and reverts the
  build; greenfield dirs are created and `git init`-ed.
- **Steerable multi-turn builds** (`async=true`): progress log tail, steer/interrupt, executable
  Definition of Done (`dod_cmd`, argv list) after each turn, bounded by `max_fail_retries` (3)
  and `max_turns` (12); a 0-file turn warns.
- **`batch_run`** — durable journaled fan-out (SQLite WAL, `resume_id` across a restart).
- **`workflow` presets** `refine_plan` (`plan_file`), `council_review` (removed in 0.3.0),
  `map_review`, `research_verify`.
- **Opt-in streaming runner** (`arun(on_line=…, log_path=…)`) with a stall guard.

### Fixed
- **Guard anti-bypass**: NFKC-normalized, zero-width-stripped matching.
- **Runtime paid-model warning** when a free lane resolves to `opencode-go/*`.
- `hidden-html-comment` guard only fires when the comment hides a directive or secret-talk.
- Removed the dead synchronous spawn path (`runner.run()`); everything goes through `arun`.
- CI matrix: Python 3.13 on Linux; macOS and Windows test 3.10 + 3.13.
- `SECURITY.md` discloses environment inheritance by delegate CLIs.

### Added (docs, layout, i18n)
- README in 6 languages (`docs/i18n/`) and a GitHub Pages landing (both removed in 0.3.0).
- Root slimmed to the conventional files; `BENCHMARKS.md`/`ARCHITECTURE.md` under `docs/`;
  `CONTRIBUTING.md`/`SECURITY.md`/`CODE_OF_CONDUCT.md` under `.github/`.
- Animated SVG banner + mark (`assets/`).
- **`CLI_BRIDGE_TRACE_FOOTER=off`** hides the `## Trace` footer in workflow reports.

### Removed (dead code)
- `server.lanes_load_status()`, `workflows.assign_roles()`; `LaneSpec.install_hint` is now
  printed by `doctor` for lanes not on PATH.

### Changed (eval v2)
- Corpus 12 → 20 fixtures (10 → 18 bugs); per-bug win/loss in the JSON output; severity rubric
  in the reviewer JSON rules (blocker / high / medium / low).

### Added (resilience)
- **`CLI_BRIDGE_<LANE>_MIN_INTERVAL_S`** (or `min_interval_s` in the config file): minimum spacing
  between spawns of one lane (`runner.pace`); different lanes never wait. Default 0.

### Added (M12)
- `files_required_to_continue` grounding gate on `debate`/`consensus` (removed in 0.3.0).
- **Debate `VOTE: confidence=<0-1>; continue=<yes|no>` footer** — parsed into a tally; the
  debate ends early when every debater votes to stop. **Convergence detection** via `difflib`
  (≥92 % similarity between rounds stops early).
- **`architect_lane`** on isolated builds: a stronger lane writes the plan, the editor lane
  implements it; graceful fallback if the architect fails.
- **`cli-bridge eval`** — council (`review_diff([N lanes])`) vs one strong model sampled K = N
  times, equal call budget, deterministic scorer (keyword AND-of-OR + file/line, greedy 1:1, no
  LLM judge), calibration gate in CI, `--live` / `CLI_BRIDGE_EVAL_LIVE=1` for real models,
  throttled arms flagged **Unreliable**. First measured run (2026-06-05, repeats=3): no clean
  winner — a strong single model caught marginally more bugs (recall 93 % vs 73 %, overlapping
  bands) with ~40 false alarms (precision 0.19); the council ~14 false alarms (precision 0.33).
  (Harness moved to `benchmarks/` in 0.3.0.)
- **`apilookup` MCP prompt**: dated, current-year documentation lookup through a web-aware lane.
- `CLI_BRIDGE_DISABLED_TOOLS` / `CLI_BRIDGE_ENABLED_TOOLS` (replaced by `CLI_BRIDGE_TOOLS` in 0.3.0).

### Changed (review quality, deliberation)
- `review_diff` / `security_review` prompts gained an anti-overengineering, diff-only line.
- **`consensus` SELECTS the peer-ranked best answer by default** (Borda); `synthesize=true` for
  the chairman blend. (Now `debate(vote=borda)`.)
- `dry_run` on `debate`/`consensus` returns a preflight data manifest (vendors, files, chars).

### Security (M11)
- **`set_lane_cost` REQUIRES a provenance note.**
- **BYO-API keys never touch argv**: curl ≥ 8.3 `--variable %MY_KEY` + `--expand-header`;
  `argv_secret_risk` validator warns in `doctor`.

### Added (debate/consensus hardening)
- **Grounding contract** `context_files` (up to 5 files read into every debater prompt).
- Fact-check pass, anti-unanimity steelman, provenance tags, brief linter (all removed in 0.3.0);
  **independent judge** (with 3+ lanes one is held out; `allow_self_judge`); **`summary_only`**;
  reports end with the pre-filled `rate_lane(...)` call.
- **Community lanes** (`examples/community-lanes.json`): Aider, Goose, Plandex, Amp, Crush,
  Amazon Q CLI, Droid — `limited` by default.

### Added (cost policy)
- **`docs/COSTS.md`** — sourced, dated free tiers, per-token pricing, subscription mechanics.
- **`set_lane_cost`** — one call sets a lane's tier + why-note, effective now, persisted.
- **The $0 council** (`examples/free-apis.json`): Groq, Cerebras, GitHub Models, OpenRouter `:free`.
- **Cost-facts freshness guard**: `doctor` warns when the snapshot is >90 days old.
- Tiers labeled "(set by you)" vs "(default — yours may differ)"; `qwen` → `paid`, `grok` →
  `limited`, gemini carries its free-tier sunset, opencode discloses the data-training tradeoff;
  every lane ships a `cost_note`.

### Added (Grok, drift-proofing, reliability)
- **Grok lane** (`ask_grok`), no hardcoded model.
- Flag-drift detection in `doctor deep` via `probe_flags` (removed in 0.3.0; `doctor --deep`
  still calls each lane).
- **Usage-policy refusals fall through** (`kind="policy"`): a delegate that refuses on policy
  grounds and exits 0 is a soft failure, skipped by cascade, never cached.
- **opencode's free model is DISCOVERED, never pinned**: only `opencode/*-free` by pattern from
  `opencode models`; never silently falls back to a paid model.

### Added (round-table, discovery, git tools, routing)
- **Round-table conversations**: `conversation: "new"` on any `ask_<lane>`, reuse the id on any
  lane; sqlite transcript survives `/compact` and restart; `CLI_BRIDGE_CONVO_MAX_CHARS` (32000),
  `CLI_BRIDGE_CONVO_MAX_STORED`.
- **Per-lane model selection incl. env-based** (Mistral via `VIBE_ACTIVE_MODEL`); **`list_models`**.
- **`consensus`** (blind answers, anonymized Borda ranking, chairman) and **`challenge`**
  (one outside lane critically reassesses a claim) — both folded into `debate`/`workflow` in 0.3.0.
- **`setup`** detects installed lanes, sorts by cost, recommends a profile + daily cap.
- **Live progress notifications** on slow fan-outs (MCP-native).
- **`commit_msg`** / **`pr_describe`** (now `git_text`), read-only.
- **`debate adversarial: true`** (for/against/neutral stances); **`severity_filter`** on reviews.
- **`rate_lane`**: score a lane 1–5 per mode; `ask_best` prefers proven lanes on this machine
  (two-rating floor); every `ask_best` answer prints the exact `rate_lane(...)` call.
- **Free synthesis via MCP sampling**: `ask_all` synthesis uses the host's own model when
  supported, else a free lane.

### Added
- **Council recap** line per delegate on every fan-out result.
- **Async jobs** (`ask_all_async` + `job_*`, now `ask_all(async=true)` + `job`).
- **Structured review**: JSON findings merged by file/line/title with agreement-based
  confidence; `output_format: markdown|json`; deterministic prechecks (secrets, dangerous shell).
- **Output guard** `CLI_BRIDGE_GUARD=off|warn|strict`.
- **Worktree-isolated write mode** (`ask_build_isolated`, now `ask_build`).
- **`ask_best`** router with modes + estimated token/credit accounting (`CREDITS_PER_1K`, `DAILY_LIMIT`).
- **Human CLI** (`cli-bridge …`) and **MCP resources** (`cli-bridge://config`, `lane-stats`, `usage-summary`).
- **`premortem`** / **`test_plan`** workflows.
- `CLI_BRIDGE_TERSE_MIN_CHARS`; eval fixtures + no-network evaluator; ruff lint in CI.

### Added (reliability & onboarding)
- **Transient retry** (`CLI_BRIDGE_RETRIES`, default 1); quota/auth/not-found/timeout never retried.
- **Mock mode** (`CLI_BRIDGE_MOCK=1`): canned answers, nothing spawned.
- `cli-bridge init` / `cli-bridge bench` (removed in 0.3.0).
- **Trace bundle** (`CLI_BRIDGE_TRACE_DIR`): per-delegation redacted JSON.
- **JSON config file** (`~/.config/cli-bridge/config.json`), env wins.
- `CLI_BRIDGE_DAILY_CREDIT_CAP`, `CLI_BRIDGE_ALLOW_LANES`, `CLI_BRIDGE_DISABLE_BUILD`.
- `ask_all`: `output_format=json`, `summary_only`, `dry_run`.
- `doctor --deep` shows each free lane's CLI version; `CLI_BRIDGE_OVERFLOW_MAX_FILES`;
  `release.yml` publishes to PyPI via Trusted Publishing.
- **`CLI_BRIDGE_MAX_PARALLEL`** (default 6) caps simultaneous spawns in `ask_all`.
- README "Known limitations"; `.github/SECURITY.md`.

### Changed
- **Empty answers fall through** (`kind="empty"`): exit 0 with no output is a soft failure,
  skipped by cascade, never cached, no cooldown.
- Findings merge collapses similarly-worded findings at the same `file:line`.
- CI runs on macOS and Windows as well as Linux.

### Initial prototype (pre-PyPI scaffold)
- MCP server: per-host self-hide, PATH detection, lane registry (claude/gpt/gemini/mistral/
  opencode/qwen/copilot) + custom lanes via JSON + BYO-API via curl, `ask_<lane>`, `ask_all`
  (+ synthesize), `ask_cascade`, `doctor`, cost profiles, telemetry + cooldown, response cache,
  `review_diff`/`security_review`/`debate`, MCP prompts, sibling-model self-consultation, opt-in
  write/build mode.
