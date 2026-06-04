# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims for
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (current-docs guard)
- **`apilookup` MCP prompt** (slash command): forces a dated, current-year documentation lookup
  through a web-aware lane (`ask_gemini`/`ask_grok`) instead of answering a library/API question
  from a stale training cutoff. Shipped as a prompt — zero tool-surface cost.

### Added (context economy — modular tool loading)
- **`CLI_BRIDGE_DISABLED_TOOLS` / `CLI_BRIDGE_ENABLED_TOOLS`**: hide tools from the listing
  (denylist) or expose only a chosen set (allowlist = one-env "lean mode"). Every host pays each
  tool's schema in context per request; the 2026 consensus is 5–15 tools with sharp degradation
  past ~20, and an unfilterable surface is the #1 documented complaint about the leading
  multi-model MCP server. `doctor`/`setup` are essential and can't be hidden.

### Changed (review quality — scope discipline)
- **Reviewers are now told not to overengineer or scope-creep.** `review_diff` / `security_review`
  prompts gained an explicit anti-overengineering + diff-only discipline line (no hypothetical
  abstractions, no unrelated rewrites/migrations) — directly counters the low-value-nit padding
  seen when dogfooding the council on this repo.

### Changed (deliberation science — selection beats synthesis)
- **`consensus` now SELECTS the peer-ranked best answer by default; synthesis is opt-in.**
  Research flipped against blending: judge-SELECTION of the single best answer wins where
  MoA-style synthesis loses to baseline (arXiv 2603.20324, effect size g=3.86; Self-MoA arXiv
  2502.00674). consensus already ranked with a deterministic Borda vote (selection-shaped) but
  then a chairman REWROTE the winner (synthesis-shaped). The default now returns the #1 answer
  verbatim + the vote table; pass `synthesize=true` for the chairman blend, labeled the weaker
  mode. One fewer lane call by default. (`ask_all synthesize` was already opt-in.)

### Added (data governance — preflight manifest M11-2)
- **`dry_run` on `debate`/`consensus` returns a preflight data manifest** — exactly which vendors
  would be queried and which files/chars (and est. tokens) would leave the machine — without
  spawning anything. The cheapest data-governance control before a multi-vendor fan-out. Shared
  file-reader feeds both the manifest and the debate context pack so they never disagree.

### Security (council blockers M11-1, M11-4)
- **`set_lane_cost` now REQUIRES a provenance note.** Every cost write must state its one-line
  why ('user: on the Go plan', 'vendor: tier sunset') — a delegate's output can't quietly steer
  the host into rewriting the cost policy, and doctor shows the note next to the tier.
- **BYO-API keys never touch argv anymore.** The shipped curl-lane examples now use curl ≥ 8.3's
  `--variable %MY_KEY` + `--expand-header "Authorization: Bearer {{MY_KEY}}"`, which imports the
  key *inside* curl — `ps` only ever shows the variable's NAME. New `argv_secret_risk` validator:
  a custom lane that still expands a `${ENV}` secret into a credential-bearing argv part gets a
  ⚠️ warning in `doctor` with the safe pattern. (Unanimous blocker from the council's
  self-critique; SECURITY.md updated.)

### Added (debate/consensus hardening — from a production field report)
- **Grounding contract** (`context_files`, debate + consensus): the tool reads up to 5 key files
  (per-file truncation, unreadable files noted, never fatal) into a CONTEXT PACK injected into
  every debater/panelist prompt. Field-tested finding: with only `cwd`, no debater reads
  anything and the council is an echo chamber of the brief.
- **Fact-check pass** (debate, default ON when a free lane exists): after the judge, a free lane
  extracts the verdict's verifiable claims (commands, model tags, versions, APIs) and reports
  what it cannot confirm under "⚠️ Fact-check" — catches a judge-approved hallucinated command
  before the host copy-pastes it.
- **Independent judge** (debate): with 3+ lanes, one lane is held out of the debate to judge it;
  with fewer, the self-judge is labeled "(also debated — sparse pool)" in the report.
  `allow_self_judge: true` restores everyone-debates.
- **Anti-unanimity steelman** (`steelman: true`): the judge now emits a structured
  `UNANIMOUS: yes|no` marker; on unanimity one lane argues the strongest case AGAINST the
  verdict and the judge re-concludes (bonus round traced in meta). Fast 4-0s get pushback.
- **Provenance tags** (debate): debaters tag claims `[brief]` / `[context]` / `[own-knowledge]`
  / `[verified]` — the echo chamber becomes visible in the output itself.
- **Brief linter** (debate): a thin brief (too short / no enumerated options / no decision
  criteria) gets a non-blocking "thin brief → thin consensus" warning in the report.
- **`summary_only`** (debate + consensus): verdict + disagreements + fact-check only, full
  per-model positions dropped (~60-80 % fewer host tokens).
- **`rate_lane` hook**: debate and consensus reports end with the pre-filled `rate_lane(...)`
  call, so the routing feedback loop feeds itself.
- **Community lanes** (`examples/community-lanes.json`): ready-to-edit experimental lanes for
  Aider, Goose, Plandex, Amp, Crush, Amazon Q CLI and Droid — `limited` by default (cost-safe)
  and drift-checkable via `doctor deep`.

### Added (honest, self-maintaining cost policy)
- **`docs/COSTS.md`** — the sourced, dated truth behind every cost tier: free tiers with exact
  limits (Groq/Cerebras/GitHub Models/OpenRouter), per-token API pricing with a "cost of a 3k/1k
  review" anchor per model, and subscription mechanics (shared buckets, exhaustion behaviour:
  hard-stop vs metered overage vs silent downgrade). Verified June 2026 against vendor pages;
  anything unconfirmable is marked UNCONFIRMED instead of guessed.
- **`set_lane_cost` tool — the cost policy maintains itself.** The counterpart of `rate_lane` for
  money: when the user says what a lane costs THEM, or the host knows a vendor changed a tier,
  one call sets the lane's tier (+ a why-note shown by doctor), effective immediately and
  persisted to the JSON config file. No code update needed for the policy to track reality.
- **The $0 council** (`examples/free-apis.json` + README section): ready-to-use BYO-API curl
  lanes for the providers with a genuinely free, card-free, hard-stop tier (Groq, Cerebras,
  GitHub Models, OpenRouter `:free`) — a real multi-model council for a user with zero
  subscriptions, with real limits quoted per lane.
- **Cost-facts freshness guard**: the verification date ships in the code; `doctor` warns when
  the snapshot is stale (>90 days) instead of letting old facts pose as current.

### Changed (honest, self-maintaining cost policy)
- **Cost tiers are now labeled for what they are.** `doctor`/`setup`/`cli-bridge init`/the config
  resource all distinguish "(set by you)" from "(default — yours may differ)" and state that
  tiers are sourced typical-plan defaults, NEVER detected from the user's account. The setup
  flow now opens with one symmetric question (flat subscriptions / metered API / mix) instead of
  presenting hardcoded guesses as "what lanes cost YOU".
- **Lane defaults corrected to sourced facts**: `qwen` → `paid` (free OAuth tier closed
  2026-04-15; the Alibaba Coding Plan ToS prohibits non-interactive use, so the only
  cli-bridge-compatible path is a metered key); `grok` → `limited` (SuperGrok/X Premium+
  required) with the documented `-p` headless flag and the official curl installer; `gemini`
  carries its free-tier sunset (2026-06-18 → Antigravity) in doctor; `opencode` discloses the
  free-period data-training tradeoff. Every built-in lane now ships a one-line sourced
  `cost_note` surfaced by doctor.

### Added (Grok lane, drift-proofing)
- **Grok lane** (`ask_grok`): built-in lane for xAI's `grok` CLI (experimental). No model is
  hardcoded — empty `model` uses the CLI's own default; pass `model=<id>` to pick one.
- **Flag-drift detection** (`doctor deep`): each installed lane is checked against its `--help` —
  if a flag cli-bridge relies on (`--sandbox`, `-m`, `-p`, …) has been renamed/removed upstream,
  doctor warns *before* the lane fails silently. Costs no quota (just `--help`). Custom JSON lanes
  derive their checked flags from the template automatically. Lanes declare `probe_flags`.

### Changed (reliability)
- **Usage-policy refusals fall through instead of posing as answers.** When a delegate refuses
  on policy grounds and still exits 0 (Claude Code prints "API Error: … unable to respond … "
  "violate our Usage Policy … Request ID: req_…"), the runner now classifies it as a soft
  failure `kind="policy"` — so `ask_cascade`/`ask_best` skip to a lane that actually answers, it
  is never cached, and a council fan-out no longer shows a refusal as if it were a real answer.
  Fingerprint requires two co-occurring phrases so a normal answer mentioning "usage policy" or
  "API Error" can't misfire. (Surfaced by dogfooding the council on the project itself.)

### Changed (drift-proofing)
- **opencode's free model is DISCOVERED, never pinned — and cost-safe.** The empty-model default
  resolves only to a `opencode/*-free` model (the $0 rate-limited tier), discovered live from
  `opencode models` and chosen by PATTERN, deterministically sorted — never a specific hardcoded
  id, so a retired free model is replaced automatically. It will NOT silently fall back to a paid
  model: a bare `opencode/*` Zen model bills per-token (API cost) and `opencode-go/*` spends prepaid
  credits, so if no `-free` model is listed it uses the free seed rather than a paid one. A pinned
  id remains only as a last-resort seed if `opencode models` itself fails.

### Added (round-table conversations, model discovery, challenge)
- **Round-table conversations**: pass `conversation: "new"` to any `ask_<lane>` to start a
  multi-turn, MULTI-LANE thread; reuse the returned id — even on a different lane — to continue.
  The shared transcript is stored locally (sqlite), so a thread SURVIVES the host's context
  reset (`/compact`) and a server restart. Recipient-aware replay (your own turns marked "You",
  others named) with a sliding-window budget (`CLI_BRIDGE_CONVO_MAX_CHARS`, default 32000) that
  keeps the newest turns and drops the oldest. New tools `conversations_list` /
  `conversation_show`; `CLI_BRIDGE_CONVO_MAX_STORED` caps how many threads are retained.
- **Per-lane model selection, including env-based**: a lane can now pick a model via an env var,
  not only a flag — Mistral (`vibe`) honours `model=` through `VIBE_ACTIVE_MODEL`. New generic
  `list_models` tool: lists a lane's models where the CLI exposes that, otherwise shows the
  resolved default model and how to choose one.
- **`consensus`**: the "LLM council" pattern, done better. Every lane answers blind, then each
  RANKS the **anonymized** answers (so no model can favour its own), the votes are aggregated
  **deterministically** (Borda count — not an LLM's vibe), and a chairman synthesizes the
  winner. Cost-bounded and ban-safe. Returns the final answer + a peer-vote ranking table.
- **`challenge`**: hand a claim to one outside lane with a critical-reassessment prompt and get
  an independent skeptical review (with an integrity guardrail — it won't manufacture
  disagreement). Pressure-test your own conclusion before acting.
- **Onboarding & guidance**: `setup` now detects installed lanes, sorts them by what they cost
  you (free / limited / paid) and recommends a concrete profile + daily cap to confirm. The MCP
  `instructions` were rewritten as a host-agnostic playbook: when to consult / when not, the
  round-table, safe delegation (`ask_build_isolated`), and spending with confidence.
- **Live progress streaming**: slow fan-outs (`ask_all`, `consensus`, `debate`) now emit MCP
  progress notifications ("3/5 lanes done"), so the host can show a live indicator instead of a
  frozen spinner — done the MCP-native way (no tmux), and a no-op when the host sends no progress
  token.
- **Git-workflow tools**: `commit_msg` (a Conventional Commit message from the staged diff, or
  the working tree if nothing is staged) and `pr_describe` (PR title + Summary/Changes/Testing
  from the branch diff + commit log vs a base). Both read-only — they emit text, never commit.
- **Debate stances + consensus agreement**: `debate` gains `adversarial: true`, which assigns
  for/against/neutral stances to the opening answers (sharper disagreement, with an integrity
  guardrail so a stance never forces a dishonest position). `consensus` now reports an agreement
  metric (how many rankers placed the winner first).
- **Review triage**: `review_diff` / `security_review` accept `severity_filter` — show only
  findings at or above a threshold (blocker > high > medium > low > info).
- **Outcome-tracked routing (`rate_lane`)**: the router LEARNS. Score a lane's answer 1–5 for a
  task-type (mode) and `ask_best` then prefers the lanes that actually win that mode **on this
  machine** — a local quality signal, stored in sqlite, that outlives the session (survives
  `/compact` and restart). Proven-good lanes jump ahead of untried ones; proven-bad sink below;
  zero feedback changes nothing (a two-rating floor before any lane steers). Every `ask_best`
  answer prints the exact `rate_lane(...)` call, and `route_plan` shows each lane's running score.
- **Free synthesis via the host (MCP sampling)**: when the host supports it, `ask_all`'s
  synthesis uses the host's OWN model as the judge — no lane spawned, no API key, no quota —
  and transparently falls back to a free lane otherwise. cli-bridge's zero-cost edge: reuse the
  model you're already running.

### Added
- **Council recap**: every `ask_all` / review / debate / premortem / test_plan result opens with
  a one-line-per-delegate digest — who answered, latency, a one-line gist — so no voice is hidden.
- **Async jobs**: `ask_all_async`, `job_status`, `job_result`, `job_cancel`, `jobs_list` — start a
  slow fan-out in the background and poll it, so it can't hit the host's tool-call deadline.
- **Structured review**: reviewers emit JSON findings, merged deterministically by file/line/title
  with agreement-based confidence (single/majority/consensus); `output_format: markdown|json`.
  Deterministic prechecks (secrets, dangerous shell) seed the findings. `security_review` adds a
  `residual_risk` section.
- **Output guard**: `CLI_BRIDGE_GUARD=off|warn|strict` scans delegate output for prompt-injection
  / tool-poisoning.
- **Worktree-isolated write mode**: `ask_build_isolated` runs a build agent in a throwaway git
  worktree and returns a diff; your real repo is never touched.
- **`ask_best`** router with modes (fast/cheap/deep/code/review/security) + estimated token/credit
  accounting (`usage_report`, `usage_budget`; per-lane `CREDITS_PER_1K`, `DAILY_LIMIT`).
- **Human CLI** (`cli-bridge …`) and **MCP resources** (`cli-bridge://config`, `lane-stats`,
  `usage-summary`, `workflow-schemas/review-diff`).
- **`premortem`** and **`test_plan`** workflows (+ MCP prompts).
- Terse preamble made leaner with a `CLI_BRIDGE_TERSE_MIN_CHARS` skip; eval fixtures + a
  no-network evaluator; ruff lint + CI lint job.

### Added (reliability & onboarding)
- **Transient retry** (`CLI_BRIDGE_RETRIES`, default 1): a delegate that fails transiently
  (non-zero exit / spawn blip) is retried with backoff, so a flaky CLI "works the first time".
  Quota/auth/not-found/timeout are never retried (sticky / would waste a call).
- **Mock / dry-run** (`CLI_BRIDGE_MOCK=1`): lanes report installed and return a canned answer
  without spawning anything — explore routing/fan-out/workflows with zero CLIs installed.
- **`cli-bridge init`**: detect installed CLIs + print the MCP wiring snippet + cost hint.
- **`cli-bridge bench`**: latency p50/p95/p99 + ok-rate + est tokens for a lane over N runs.
- **Trace bundle** (`CLI_BRIDGE_TRACE_DIR`): per-delegation redacted JSON (argv, timing, output)
  for reproducible debugging / ban-safe audit.

### Added (from the council audit — round 2)
- **JSON config file** (`~/.config/cli-bridge/config.json`): friendly alternative to env vars,
  loaded at startup with env-wins precedence (progressive disclosure — defaults → file → env).
- **Cost-safety & team controls**: `CLI_BRIDGE_DAILY_CREDIT_CAP` (hard stop on estimated paid
  spend), `CLI_BRIDGE_ALLOW_LANES` (allowlist), `CLI_BRIDGE_DISABLE_BUILD` (force read-only).
- **`ask_all`**: `output_format=json`, `summary_only` (recap+synthesis, fewer tokens), `dry_run`
  (preview lanes + estimated cost without spawning).
- **`doctor --deep`** now shows each free lane's CLI version (drift detection); `bench --all`
  benchmarks every free lane into a table; `BENCHMARKS.md` explains how to generate real numbers.
- Overflow dir gains a file-count cap (`CLI_BRIDGE_OVERFLOW_MAX_FILES`). `release.yml` publishes
  to PyPI via Trusted Publishing on a version tag.

### Added (from the council audit)
- **`CLI_BRIDGE_MAX_PARALLEL`** (default 6): caps simultaneous delegate spawns in `ask_all` so a
  wide council (many custom lanes) can't OOM a small machine or burst quota.
- README: "Works in IDE MCP hosts too" + an honest **Known limitations** list (ban-safe ToS
  caveat, in-process jobs, heuristic guard, estimated tokens, BYO-API argv exposure, experimental
  lanes). SECURITY.md notes the BYO-API curl key-in-argv exposure + mitigation.

### Changed
- **Empty answers fall through.** A delegate that exits 0 but prints NOTHING (seen with `agy` /
  Antigravity in print mode) is now a soft failure (`kind="empty"`) instead of a "successful"
  blank — so `ask_cascade` / `ask_best` skip it and return a lane that actually answers, and it's
  never cached. Not retried, not a cooldown (it's per-call, not lane health).
- Findings merge now also collapses **similarly-worded** findings at the same `file:line`
  (token-overlap similarity), not just exact-title matches — so two models describing the same
  bug differently merge into one entry with higher confidence. None-location findings stay
  exact-only (no over-merging).
- CI test matrix runs on **macOS and Windows** as well as Linux (portability is a stated
  invariant; now it's actually exercised). POSIX-shell-only runner tests skip on Windows.

## [0.1.0]
- Initial MCP server: per-host self-hide, PATH detection, lane registry (claude/gpt/gemini/
  mistral/opencode/qwen/copilot) + custom lanes via JSON + BYO-API via curl, `ask_<lane>`,
  `ask_all` (+ synthesize), `ask_cascade`, `doctor`, cost profiles, telemetry + cooldown,
  response cache, `review_diff`/`security_review`/`debate`, MCP prompts, sibling-model
  self-consultation, opt-in write/build mode.
