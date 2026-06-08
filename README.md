<div align="center">

<img src="assets/banner.gif" width="860" alt="cli-bridge — your assistant borrows the powers of every AI CLI you already have: huge-context reads, vision, parallel builds, cross-vendor checks">

**English** · [Français](docs/i18n/README.fr.md) · [简体中文](docs/i18n/README.zh-CN.md) · [Español](docs/i18n/README.es.md) · [Português (BR)](docs/i18n/README.pt-BR.md) · [日本語](docs/i18n/README.ja.md) · [Deutsch](docs/i18n/README.de.md)

</div>

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![status](https://img.shields.io/badge/status-pre--public%20(not%20on%20PyPI)-lightgrey)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**Your assistant, with the powers of every CLI you already have.**

> **No API keys · no token extraction · no Node · no daemon · stdlib + `mcp` only.**

The assistant you're talking to can't read a 2M-token repo in one pass, can't see a screenshot,
can't generate an image, and can't check its own work without bias. The other AI CLIs you've
**already installed and logged into** — Claude Code, Codex, Gemini, opencode, plus local models via
Ollama — each do something yours can't. `cli-bridge` is a [Model Context Protocol](https://modelcontextprotocol.io)
server that lets your assistant **borrow them**: it spawns the official CLI as a subprocess (exactly
as you'd run it by hand — no keys, no token extraction) and hands the result back.

---

## The four levers

cli-bridge isn't one feature — it's four things your assistant gains. Every tool below maps to one:

1. **Borrow** — reach a capability your host lacks (vision, a 1M-token window, image generation, a model that's simply better at *this*).
2. **Spread** — when one subscription caps out, keep going on another lane you already pay for.
3. **Offload** — fan laborious, parallel grunt-work across cheap/free lanes while you build elsewhere.
4. **Verify** — put a *different vendor family* in the reviewer's seat. The one thing a single-vendor tool structurally can't do.

```
ask_gemini(task="find the bug across ./src", cwd="path/to/repo")                 # Borrow — 1M-token context
ask_gemini(task="what's wrong in this UI?", images=["screenshot.png"])           # Borrow — vision (experimental)
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png", zone="assets")  # Borrow — image by path, no API key (paid ChatGPT plan)
ask_cascade(task="finish wiring this endpoint")                                  # Spread — cheapest→strongest, skips capped lanes
batch_run(tasks=[...], max_calls=20, max_credits=2.0)                            # Offload — bounded, resumable fan-out
workflow(preset="jury", task="is this migration safe?", author_lane="gpt")       # Verify — cross-family vote, fail-closed
```

`cli-bridge build <lane> "<task>"` delegates a real build to another model in a **throwaway git
worktree** and hands back a **diff** — your repo is never touched until you apply it yourself.

<p align="center">
<img src="assets/demo-borrow.gif" width="860" alt="cli-bridge build: opencode adds a function in a throwaway worktree and returns a reviewable diff; the real repo stays clean">
</p>

---

## Quick start (≈5 min)

```bash
# Run it (no install) — installs straight from the repo:
uvx --from git+https://github.com/JoaoBerne/cli-bridge-mcp cli-bridge doctor
# or, from a clone:  python -m cli_bridge
```

> **Not on PyPI yet.** A registry release is GO-gated (see [Roadmap](#roadmap)). Until then, install
> from git with the `uvx --from git+…` form above — plain `uvx cli-bridge-mcp` will fail to resolve.

Point your MCP host at the same command. Example config (`~/.claude.json` or `.mcp.json`) in
[`examples/mcp.example.json`](examples/mcp.example.json); `cli-bridge doctor` reports which CLIs are
detected and their resolved paths.

### Lanes

**Built-in:** Claude Code, Codex, Gemini (+ Antigravity `agy`), opencode, **Ollama (local, $0,
offline)**, Qwen Code, Copilot, Grok.

**Local runtimes** beyond Ollama — **LM Studio · MLX · llama.cpp** — ship as zero-code recipes: point
`CLI_BRIDGE_LANES_FILE` at [`examples/lmstudio.lane.json`](examples/lmstudio.lane.json),
[`mlx.lane.json`](examples/mlx.lane.json), or [`llamacpp.lane.json`](examples/llamacpp.lane.json).
(Several local runtimes of the *same* weights give correlated answers — real council diversity comes
from distinct vendors.)

**Community lanes** (`examples/community-lanes.json`, experimental until you declare their cost): Aider,
Goose, Plandex, Amp, Crush, Amazon Q Developer CLI, Droid. **Anything else is ~3 lines of JSON** — see
[`examples/`](examples/).

---

## The toolbox

Grouped by what you're trying to do. `CLI_BRIDGE_LEAN=1` gives a curated ~12-tool surface;
`CLI_BRIDGE_DISABLED_TOOLS` / `CLI_BRIDGE_ENABLED_TOOLS` hide/show any.

### Consult (read-only)
| Tool | What it does |
|------|--------------|
| `ask_<lane>` | Ask one CLI — `ask_claude`/`ask_gpt`/`ask_gemini`/`ask_mistral`/`ask_opencode`/`ask_ollama` (+ `qwen`/`grok`/`copilot` when installed). Supports `role=`, `conversation` (round-table memory), `images=[…]` on Gemini. |
| `ask_all` | Same question to every *free* lane in parallel + a **disagreement score** (= uncertainty signal). |
| `ask_cascade` | Deterministic order, stops at first good answer, skips cooled-down lanes. |
| `ask_best` | Router picks the lane by `mode` (`fast/cheap/deep/code/review/security`) + your `rate_lane` scores. |
| `ask_all_async` + `job_status`/`job_result`/`job_cancel`/`jobs_list` | Fire `ask_all` as a background job. |
| `consensus` | N lanes answer, peers rank to **select** the best (selection beats synthesis). |
| `challenge` | One lane plays skeptic against a conclusion you supply. |
| `conversations_list` / `conversation_show` | List / read persistent round-table threads. |

### Build (opt-in write)
| Tool | What it does |
|------|--------------|
| `ask_build` | Delegates a real build. `mode=isolated` (default) → **diff**; `mode=direct` writes into a declared `zone` (per-zone lock + violation check); `async=true` runs it as a steerable job. Non-text outputs return **by path**. |
| `ask_build_isolated` | Alias for `ask_build mode=isolated` — always a diff, never touches your tree. |
| `job_tail` / `build_steer` | Stream a build's log / queue a steering instruction (`interrupt=true` cuts the current turn). |

Async builds run against an executable **Definition-of-Done** gate (`dod_cmd`) — success is *tested*, not trusted.

### Review & verify
| Tool | What it does |
|------|--------------|
| `review_diff` | Structured diff review → findings (severity, file, rationale), merged across lanes with single/majority/consensus confidence. |
| `security_review` | OWASP-oriented, severity-ranked pass + a `residual_risk` section. |
| `debate` | Models critique each other over bounded rounds → `VOTE` footer + convergence early-stop; an independent judge concludes. |
| `premortem` / `test_plan` | Failure-mode analysis / prioritized test plan from a diff or description. |
| `commit_msg` / `pr_describe` | Conventional-Commit message / PR title+body. Read-only. |
| `workflow(preset=…)` | Named pipelines: `jury`, `verify_repair`, `refine_plan`, `fanout_compare`, `council_review`, `map_review`, `research_verify`. |

### Orchestrate & operate
| Tool | What it does |
|------|--------------|
| `batch_run` | Durable, **journaled** fan-out. `dry_run=true` returns a cost envelope; `max_calls`/`max_credits` cap spend; `resume_id` resumes across a restart. |
| `usage_report` / `usage_budget` | Estimated token/credit accounting (chars/4) + budget vs a daily cap. |
| `rate_lane` / `route_plan` | Score a lane 1–5 for a mode / preview a cascade's order. |
| `lane_stats` / `reset_lane_state` / `set_lane_cost` | Per-lane health & cooldowns / clear counters / record what a lane costs *you*. |
| `doctor` / `setup` | Detect installed CLIs; `doctor deep` validates each lane against its own `--help`. |
| `list_models` / `list_<lane>_models` | List a lane's models where the CLI exposes them. |

There's also a **human CLI** (`cli-bridge doctor|ask|ask-all|ask-best|build|review-diff|eval|…`) — the
same engine from your terminal or CI (`--json` everywhere).

---

## How it works

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
       keeps the host's own lane out of fan-out · only shows installed, enabled CLIs
       kills the whole process tree on timeout/cancellation · redacts secrets
       classifies errors (auth/limit/failed) · spills huge output to a file
```

No network calls of its own. No keys stored. It runs the same binaries you already trust, in your
working directory, and hands the answer back.

**Writes are contained, two ways:** `isolated` (default) edits a throwaway worktree → diff, your tree
untouched; `direct` writes real files **only inside a `zone` you declare**, behind a per-zone lock —
so you and a delegate can work different zones concurrently, undo is zone-scoped. Delegate re-entry is
depth-capped (`CLI_BRIDGE_MAX_DEPTH`, default 1) so a misconfigured delegate can't fork-bomb the council.

<div align="center">
<img src="assets/demo.gif" width="860" alt="cli-bridge security-review demo: a committed auth bypass is caught by a cross-vendor council, merged into one severity-ranked report, $0 on free lanes">

_Real run (2.2× speed): `security-review` fans OWASP roles across free models in parallel; they flag a committed auth bypass **blocker**, and `usage` shows the receipts._
</div>

---

## Why cli-bridge (not another "call other models" MCP)

- 🛡️ **Ban-safe by design.** Spawns each model's **official CLI**, exactly as you'd run it by hand — no token extraction, no API-key reuse. Each CLI handles its own auth and billing.
- 💸 **Cost-safe defaults.** `ask_all` / `ask_cascade` build a *free* council and never touch paid quota unless you ask. Tiers are sourced from published plans ([docs/COSTS.md](docs/COSTS.md)), **never detected from your account**; override with `CLI_BRIDGE_<LANE>_COST=free|limited|paid`.
- 🔌 **Works from any host** that speaks MCP over stdio (Claude Code, Codex, Cursor, VS Code, Zed). A local model can even be the host — see [`examples/local-first-host.md`](examples/local-first-host.md).
- 🧭 **Cross-vendor is the moat.** A *different vendor* in the reviewer's seat — what a single-vendor tool can't offer. Same-family subagents can only self-confirm.

→ Per-CLI strengths & limits (dated, churns fast): **[docs/COMPARISON.md](docs/COMPARISON.md)**.

---

## The honest part

"More models = better" is *fragile* — big models share training data, so their errors correlate. We
measured our own central claim (`cli-bridge eval`, no LLM judge): a diverse council did **not** catch
more bugs than one strong model — it cut false alarms **~2×**. Same catch rate, far less noise.
**Precision is the product, not recall.** The harness ships — confirm it on *your* CLIs; numbers
either way in [docs/BENCHMARKS.md](docs/BENCHMARKS.md). This unites **capabilities, not mind**:
stateless spawns, spawn latency/cost, uneven quality, host always drives. Orchestration, not fusion.

### Known limitations
- **Ban-safe = no token/key extraction**, not a blanket guarantee — non-interactive CLI use isn't formally sanctioned everywhere. Use your own accounts within their terms.
- **Async jobs are in-process** — a restart marks running jobs `interrupted`; `batch_run`/`workflow` journal and resume via `resume_id`.
- **The injection guard is heuristic** — treat delegate output as data, not instructions.
- **Token/credit figures are estimates** (chars/4); **cost tiers are sourced defaults, not detection** (`doctor` warns when stale).
- **Experimental** (`qwen`, `copilot`, `grok`, community lanes, Gemini `images=`) — `doctor deep` checks flags against each CLI's `--help`.

---

## Roadmap

See [`CHANGELOG.md`](CHANGELOG.md) for shipped history. **Exploring (not shipped):** an
**independent-oracle** verify mode (a cross-family lane writes tests from the *spec*, blind to the
implementation) and tighter **limit-aware failover**. Big inter-agent "bus" ideas (recursive spawn,
shared state, wire protocol) are a *direction*, not a shipped protocol — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## References

Design choices map to the literature; every entry was checked against its source (authors + venue).

| Paper | ID | What it backs |
|-------|----|--------------------|
| Du et al. — *Improving Factuality and Reasoning via Multiagent Debate* | [2305.14325](https://arxiv.org/abs/2305.14325) | `debate`: critique beats one model alone |
| ReConcile — *Round-Table Conference Improves Reasoning* | [2309.13007](https://arxiv.org/abs/2309.13007) | `debate` convergence + confidence-weighted consensus |
| Mixture-of-Agents | [2406.04692](https://arxiv.org/abs/2406.04692) | layered aggregation across diverse models (and its limits) |
| Chain-of-Agents | [2406.02818](https://arxiv.org/abs/2406.02818) | role-specialized multi-agent pipelines |
| CriticGPT — *LLM Critics Help Catch LLM Bugs* | [2407.00215](https://arxiv.org/abs/2407.00215) | `review_diff` / `security_review`: a critic catches bugs |
| Perez et al. — *Discovering Language Model Behaviors* (sycophancy) | [2212.09251](https://arxiv.org/abs/2212.09251) | why a same-family judge is weak → cross-vendor `jury` |
| Wynn, Satija & Hadfield — *Talk Isn't Always Cheap* | [2509.05396](https://arxiv.org/abs/2509.05396) | debate failure modes → fail-closed verdicts, bounded rounds |
| CONSENSAGENT — *Consensus via Sycophancy Mitigation* (Findings of ACL 2025) | [ACL 2025](https://aclanthology.org/2025.findings-acl.1141/) | sycophancy → "earn their seat" / anonymized peers |
| Maryanskyy — *When Agents Disagree: The Selection Bottleneck* | [2603.20324](https://arxiv.org/abs/2603.20324) | `consensus`: **selection > synthesis** |

> *Talk Isn't Always Cheap* (2509.05396) is **Wynn, Satija & Hadfield** — a popular framework miscites
> it as "Xiong et al." We double-check attributions, and flag it because honesty is the whole pitch.

## Development

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration; no real CLI or network needed
```

## License

MIT

---

<div align="center">
<img src="assets/mark.gif" width="84" alt="cli-bridge">

<sub>one side · bridged to a council</sub>
</div>
