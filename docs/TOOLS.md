# cli-bridge — tool reference

The default surface is 15 fixed tools plus one `ask_<lane>` per installed CLI. `CLI_BRIDGE_TOOLS`
changes it: `all` = everything registered (adds `batch_run`, `reset_lane_state`); a comma list =
exactly those names (+ `doctor`, `setup` and every `ask_<lane>`, never hidden); the word `default`
in a list expands to the default set (`CLI_BRIDGE_TOOLS=default,batch_run`). Hosts cache tool
names — restart the host after changing it.

Shared parameters on most tools: `task`, `cwd` (empty = host workspace root), `timeout_s`
(default 120, max 900), `include_paid` (default false; refused under `CLI_BRIDGE_PROFILE=saver`),
`dry_run` (preview lanes/order/cost without spawning), `async` (return a `job_id`, manage with `job`).

← Back to the [README](../README.md).

### Consult (read-only)
| Tool | What it does | Parameters that matter |
|------|--------------|------------------------|
| `ask_<lane>` | Ask one CLI: `ask_claude`, `ask_gpt` (Codex), `ask_gemini`, `ask_mistral`, `ask_opencode`, `ask_ollama`, `ask_apple` (on-device `fm`), and `ask_qwen` / `ask_copilot` / `ask_cursor` / `ask_grok` when installed; `ask_applepcc` appears once `APPLE_FM_SERVE_URL` is set. Returns a thread id you can reuse on any lane. | `model`, `effort`, `agent=plan\|build` (build EDITS files), `role` (architect / devil / oracle / planner / reviewer / security / simplifier, or an inline persona), `conversation`, `images=[…]` (vision lanes, see below) |
| `ask_all` | Same question to every free lane in parallel, answers side by side + a disagreement score. | `synthesize`, `summary_only`, `output_format=markdown\|json`, `dry_run`, `async` (per-lane timeout max 60 s) |
| `ask_cascade` | One answer with fallback: cheapest→strongest, skips cooled-down lanes, moves on after quota/auth/timeout/failure. | `dry_run=true` explains the order without spawning |
| `ask_best` | The router picks one lane by `mode` from cost, health, latency and your `rate_lane` scores, then runs it with fallback. | `mode=fast\|cheap\|deep\|code\|review\|security`, `dry_run` |
| `conversations` | Round-table threads: no `id` = list recent threads; `id` = the full transcript. | `id` |
| `list_models` | Models reachable through a lane (or its default + how to choose). | `lane` |

**Vision (`images=[…]`).** Each lane declares how a path is passed, so you always pass paths:

| Lane | Shape | Cost |
|---|---|---|
| `apple` | `--image <path>` | free, on-device, offline |
| `ollama` | bare path in the prompt | free, local — needs a multimodal model pulled |
| `opencode` | `-f <path>` | free on `*-free` models |
| `gpt` | `-i <path>` | limited (plan quota) |
| `gemini` | `@<path>` in the prompt | limited; unreliable under `agy` |

Whether the image is actually *read* depends on the model behind the lane, not the lane.

### Build (opt-in write)
| Tool | What it does | Parameters that matter |
|------|--------------|------------------------|
| `ask_build` | Delegates real implementation work. `mode=isolated` (default) edits a throwaway worktree and returns a **diff** (`apply=true` lands it as unstaged changes via `git apply --check`, all-or-nothing); `mode=direct` writes real files only inside `zone` under `target_dir` (per-zone lock, post-turn out-of-zone check, zone-scoped undo). Non-text outputs come back by path. | `lane` (empty = first free build-capable), `architect_lane` (isolated: a stronger lane plans first), `mode`, `zone`, `target_dir`, `apply`, `dry_run` (direct: render the brief only), `async` (direct: steerable job), `dod_cmd` (argv list run after each turn), `max_turns` (12), `max_fail_retries` (3) |

### Review & verify
| Tool | What it does | Parameters that matter |
|------|--------------|------------------------|
| `review_diff` | Several lanes review a git diff with different focuses, one lane merges into a severity-ranked report (findings carry a category: security / correctness / scope / ambiguity / performance / ops). | `focus=code\|security` (security = OWASP roles: injection, auth, secrets & crypto, data exposure), `base`, `diff`, `output_format=markdown\|json`, `severity_filter` |
| `debate` | Lanes answer, see each other, revise over bounded rounds, an independent judge concludes. | `vote=judge\|borda` (borda: no rounds, blind answers peer-ranked, winner returned verbatim; `synthesize=true` blends instead), `rounds` (1, max 3), `adversarial`, `context_files` (up to 5), `summary_only`, `allow_self_judge`, `dry_run` |
| `workflow` | One of eight presets over the durable batch substrate, all resumable (`resume_id`) and async-able. | `preset=refine_plan` (`plan_file`, `angles`) · `map_review` (`files`, `lane`) · `research_verify` (`questions`) · `fanout_compare` (`lanes`, also `lane:model` entries, `judge_lane`) · `converge` (`author_lane`, `arbiter_lane`, `peer_lanes`, `verifiers`, `max_rounds`) · `premortem` (`task` = the plan) · `test_plan` (`task` or `base`/`diff`) · `challenge` (`task` = the claim, `lane`) |
| `git_text` | Read-only git → text via one lane. Never commits. | `kind=commit` (Conventional Commit from the staged diff, else working tree) · `kind=pr` (title + Summary/Changes/Testing vs `base`, default `origin/main`), `lane` |

`converge` is the governance loop: an author drafts, an independent arbiter commits a blind
verdict, anonymized cross-family peers review, the arbiter adjudicates every issue with a reason,
then revise-or-converge. It converges only when the peers approve and no blocker remains.

### Operate
| Tool | What it does | Parameters that matter |
|------|--------------|------------------------|
| `job` | Manage background jobs (`ask_all` / `workflow` / `batch_run` / `ask_build` with `async=true`). | `action=status\|result\|cancel\|list\|tail\|steer`, `job_id` (all but list), `offset` (tail), `instruction` + `interrupt` (steer) |
| `rate_lane` | Score a lane 1–5 for a `mode` so `ask_best` prefers what wins on this machine; the note is shown as a past lesson at pick time. | `lane`, `score`, `mode`, `note` |
| `set_lane_cost` | Record what a lane costs *you*; effective now, persisted to the config file. | `lane`, `cost=free\|limited\|paid`, `note` (required) |
| `doctor` | Installed CLIs, resolved paths, host, cost tiers and their source, per-lane runs today. | `deep=true` live-probes each free lane |
| `setup` | The cost-profile choice (saver / balanced / max) to walk the user through. | — |
| `batch_run` (hidden by default) | Durable journaled fan-out over many independent tasks. | `tasks`, `max_concurrency`, `max_calls`, `max_credits`, `dry_run`, `resume_id`, `async` |
| `reset_lane_state` (hidden by default) | Clear a lane's cooldown and failure counters. | `lane` |

Usage and lane health are MCP resources, not tools: `cli-bridge://config`,
`cli-bridge://lane-stats`, `cli-bridge://usage-summary`. One MCP prompt ships: `apilookup`.

### Human CLI

`cli-bridge doctor [--deep] | set-cost <lane> <tier> --note … | ask <lane> … | ask-all | ask-best --mode … |
build <lane> "<task>" [--architect <lane>] [--apply] | review-diff | security-review | test-plan |
premortem | stats | usage | jobs` — the same engine from a terminal; `--json` where it applies.
