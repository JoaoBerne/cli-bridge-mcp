# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims for
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

### Changed
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
