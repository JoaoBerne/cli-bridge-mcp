# cli-bridge — full tool reference

Every tool, grouped by what you're trying to do. Run `CLI_BRIDGE_LEAN=1` for a curated ~12-tool
surface; hide/show any with `CLI_BRIDGE_DISABLED_TOOLS` / `CLI_BRIDGE_ENABLED_TOOLS`.

← Back to the [README](../README.md).

### Consult (read-only)
| Tool | What it does | Reach for it when |
|------|--------------|-------------------|
| `ask_<lane>` | Ask one specific CLI — `ask_claude`, `ask_gpt` (Codex), `ask_gemini`, `ask_mistral`, `ask_opencode`, `ask_ollama`, `ask_apple` (Apple Foundation Models, on-device), and `ask_qwen`/`ask_grok`/`ask_copilot`/`ask_cursor` when installed, plus the opt-in `ask_openrouter` (`OPENROUTER_API_KEY`) and `ask_applepcc` (`APPLE_FM_SERVE_URL`) — each appears only once its env var is set. Supports `role="reviewer\|security\|planner\|devil"`, `conversation` (round-table memory — every ask auto-returns a reusable thread id, so any answer is resumable on any lane), and `images=[…]` on the five vision lanes (see below). | You want a particular model's strength, persona, or modality. |
| `ask_all` | Same question to every *free* lane in parallel; returns each answer **plus a disagreement score**. `synthesize: true` adds an agree/disagree summary. | You want breadth fast and a signal of where models diverge (= uncertainty). |
| `ask_cascade` | Tries lanes in a deterministic order, stops at the first good answer, skips cooled-down lanes; optional confidence-escalation. | You want resilience: a capped/failing lane is skipped automatically. |
| `ask_best` | A router picks the most suitable lane by `mode` (`fast/cheap/deep/code/review/security`) + your `rate_lane` scores. | You don't want to choose a lane by hand. |
| `ask_all_async` + `job_status`/`job_result`/`job_cancel`/`jobs_list` | Fire `ask_all` as a background job (id in <1s). | The fan-out is slow and you want to keep working. |
| `consensus` | N lanes answer, then peers rank to **select** the best (selection beats synthesis). | A single defensible answer matters more than a blend. |
| `challenge` | One lane plays skeptic against a conclusion you supply. | You want your own reasoning attacked before you commit. |
| `conversations_list` / `conversation_show` | List / read persistent round-table threads (survive `/compact` and restarts). | You want to recover or read a multi-model thread. |

**Vision (`images=[…]`).** Five lanes accept image paths; cli-bridge emits whichever shape that CLI
wants, so you always just pass paths:

| Lane | How the path is passed | Cost |
|---|---|---|
| `apple` | `--image <path>` | free, on-device, unmetered, offline |
| `ollama` | bare path in the prompt (the CLI resolves it) | free, local — needs a multimodal model pulled |
| `opencode` | `-f <path>` | free on `*-free` models |
| `gpt` | `-i <path>` | limited (plan quota) |
| `gemini` | `@<path>` in the prompt | limited ⚠ unreliable under `agy`, which may route the file through a `read_file` tool that headless mode auto-denies |

⚠ **Vision is a property of the model, not the lane.** On the same image, Apple's on-device model
transcribed every line correctly while opencode's default free model replied *"model lacks vision"*.
cli-bridge can't detect this — pick a lane whose model you know is multimodal.

### Build (opt-in write)
| Tool | What it does | Reach for it when |
|------|--------------|-------------------|
| `ask_build` | Delegates a real build. `mode=isolated` (default) edits a throwaway worktree → **diff** (`apply=true` lands it in your tree as unstaged changes, all-or-nothing via `git apply --check`); `lane` is optional (default: first free build-capable); `mode=direct` writes into a declared `zone` (per-zone lock + post-turn zone-violation check). `async=true` runs it as a steerable job. Non-text outputs come back **by path** (artifact-return). | You want work *done*, not just suggested — review-gated or hands-off. |
| `ask_build_isolated` | Convenience alias for `ask_build` with `mode=isolated` — always returns a diff, never touches your tree. | You want the safe diff path by name, without setting `mode`. |
| `job_tail` | Streams a running build's progress log (byte-offset). | You want to watch a delegate work. |
| `build_steer` | Queues a steering instruction for the next turn, or `interrupt=true` cuts the current turn (files kept). | You need to course-correct mid-build without restarting. |

Async builds run against an executable **Definition-of-Done** gate (`dod_cmd`) — the delegate's claim
of success is *tested*, not trusted.

### Review & verify
| Tool | What it does | Reach for it when |
|------|--------------|-------------------|
| `review_diff` | Structured review of a diff → findings (severity, **category** — security/correctness/scope/ambiguity/performance/ops — file, rationale), deterministically merged across lanes with single/majority/consensus confidence. | Before a change lands. |
| `security_review` | OWASP-oriented, severity-ranked security pass + a `residual_risk` section. | The change touches auth, input handling, secrets. |
| `debate` | Models critique each other over bounded rounds, ending with a `VOTE` footer + convergence early-stop; an independent judge concludes. | A genuinely contested decision. |
| `premortem` / `test_plan` | Failure-mode analysis of a plan / a prioritized test plan from a diff or description. | Before writing code. |
| `commit_msg` / `pr_describe` | A Conventional-Commit message from your staged diff / a PR title+body from the branch. Read-only — emits text. | You're about to commit or open a PR. |
| `workflow(preset=…)` | Named pipelines: **`converge`** (governance loop — independent arbiter blind verdict → anonymized cross-vendor peers → reasoned adjudication → revise/converge; guards: blind-verdict-first, no-silent-dismissal, no-self-approval), `jury` (cross-family k-of-N vote, fail-closed), `verify_repair` (cross-model build→review→repair loop), `refine_plan`, `fanout_compare`, `council_review`, `map_review`, `research_verify`. | You want a vetted multi-step pattern in one call. |

### Orchestrate
| Tool | What it does | Reach for it when |
|------|--------------|-------------------|
| `batch_run` | Durable, **journaled** fan-out over many tasks. `dry_run=true` returns a cost envelope (nothing spawned); `max_calls`/`max_credits` cap spend; `resume_id` replays finished tasks and runs only the rest across a restart. | Bulk work you want bounded and crash-safe. |

### Operate
| Tool | What it does | Reach for it when |
|------|--------------|-------------------|
| `usage_report` / `usage_budget` | Estimated token/credit accounting (chars/4 — honestly labeled an estimate) + budgeting vs a daily cap. | You want to see the bill / set a cap. |
| `rate_lane` / `route_plan` | Score a lane 1–5 for a mode so `ask_best` learns your stack / preview the order a cascade would try. | You want the router to improve over time. |
| `lane_stats` / `reset_lane_state` | Per-lane health, cooldowns, and the "earn their seat" jury signal / clear a lane's counters. | A lane is misbehaving, or you want the seat report. |
| `set_lane_cost` | Record what a lane costs *you* ("Codex is free on my plan") — persisted, no `setup` needed. | You tell it a pricing fact in passing. |
| `doctor` / `setup` | Detect installed CLIs + resolved paths; `doctor` with `deep=true` (CLI: `doctor --deep`) validates each lane against its own `--help` on your machine. | First run, or when a lane breaks. |
| `list_models` / `list_<lane>_models` | List a lane's models. Where the CLI has no `models` command but caches what the server said your account may use (`LaneSpec.models_file`), cli-bridge reads that instead — and names those ids in the `model` parameter's description, so the choice is informed *before* you make it rather than after. Best-effort: an absent or reshaped cache silently falls back. | You want to pick a specific model, or to find out your plan already includes a better one. |

There's also a **human CLI** (`cli-bridge doctor|ask|ask-all|ask-best|build|review-diff|eval|…`) — the
same engine from your terminal or CI (`--json` everywhere). `cli-bridge build <lane> "<task>"`
delegates a real build to a lane in a throwaway worktree and prints the **diff** — your repo is never
touched.
