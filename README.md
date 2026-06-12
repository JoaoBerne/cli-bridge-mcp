<!-- mcp-name: io.github.JoaoBerne/cli-bridge-mcp -->
<div align="center">

<img src="https://raw.githubusercontent.com/JoaoBerne/cli-bridge-mcp/main/assets/banner.gif" width="860" alt="cli-bridge — your assistant borrows the powers of every AI CLI you already have: huge-context reads, vision, parallel builds, cross-vendor checks">

**English** · [Français](docs/i18n/README.fr.md) · [简体中文](docs/i18n/README.zh-CN.md) · [Español](docs/i18n/README.es.md) · [Português (BR)](docs/i18n/README.pt-BR.md) · [日本語](docs/i18n/README.ja.md) · [Deutsch](docs/i18n/README.de.md)

</div>

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp)
![stars](https://img.shields.io/github/stars/JoaoBerne/cli-bridge-mcp?style=flat&color=yellow)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-Apache%202.0-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**Your assistant is only as good as the one model you opened.** cli-bridge is a
[Model Context Protocol](https://modelcontextprotocol.io) server that lets it borrow the *other* AI
CLIs you already run — a bigger context, vision, a free second opinion from a *different vendor*, or a
delegated build that comes back as a reviewable diff.

> **No API keys · no token extraction · no Node · no daemon · stdlib + `mcp` only.**

### In one sentence

You're talking to one AI assistant. You've also installed and logged into others — Claude Code,
Codex, Gemini, opencode, Ollama. **cli-bridge connects them**: when your assistant needs something
it can't do alone, it asks one of the other CLIs and hands you the result.

### The problem it solves

Whatever assistant you're using has hard limits. It can't read a 2M-token repo in one pass, can't
see a screenshot, can't hand you a generated image, and can't check its own work without bias — but
*some other CLI on your machine can do each of those*. cli-bridge is the bridge between them: it
spawns the official CLI as a subprocess (exactly as you'd run it by hand — no keys, no token
extraction) and returns the answer to your assistant.

The result: one assistant whose ceiling on every axis is the *best* tool in your toolbox, not the
one you happened to open.

---

## The 10-second demo

You're in Claude. Claude can't hand you an image. Codex can — natively with `gpt-image-2`, or by
writing a script that renders one. For a precise layout like a social card, have it script and run it:

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png — write a script that renders it, then run it", zone="assets")
→ Codex writes assets/card.png · you get the path back, never a binary blob (artifact-return)
```

Your assistant just gained an ability it doesn't have. That's the whole idea — now scale it to
giant-context reads, vision, parallel grunt-work, and independent cross-vendor verification.

_(Codex generates the image with **`gpt-image-2`**, a real text-to-image model built into the CLI —
counted against your ChatGPT plan's usage, no separate API key (image generation needs a **paid**
plan; it's not on the Free tier). It comes back as a **path**, not a blob, because binaries travel by
artifact-return, not the text channel. A build lane can also *render* charts, diagrams or SVGs by
writing code, when that's the better fit.)_

### …and it delegates real work, safely

`cli-bridge build <lane> "<task>"` hands the job to another model running in a **throwaway git
worktree**, then gives you back a **diff** — your repo is never touched until you apply it yourself.

<p align="center">
<img src="https://raw.githubusercontent.com/JoaoBerne/cli-bridge-mcp/main/assets/demo-borrow.gif" width="860" alt="cli-bridge build: opencode adds a function in a throwaway worktree and returns a reviewable diff; the real repo stays clean">
</p>

---

## What you get — the four levers

cli-bridge isn't one feature, it's **four abilities your assistant gains**. Get these and every tool
below slots into place:

1. **Borrow** — reach a capability your assistant lacks (vision, a 1M-token context window, a file a
   coding agent generates, a model that's simply better at *this*).
2. **Spread** — when one subscription hits its limit, keep going on another lane you already pay for.
3. **Offload** — fan laborious, parallel grunt-work across cheap/free lanes while you build elsewhere.
4. **Verify** — have a *different vendor family* check the work, because a model can't catch its own
   blind spots. This is the one thing a single-vendor tool structurally cannot do.

---

## What this unlocks

Each block: one sentence of *when you reach for it*, the exact call, and *what you get back*.

### Borrow abilities your assistant doesn't have
Every CLI has a different superpower, and each runs non-interactively — so cli-bridge can spawn it.
Borrow the one your host lacks (it must be installed + logged in):

| Superpower | Which CLI has it | Borrow it when |
|------------|------------------|----------------|
| **Images** | Codex (`gpt-image-2`, **no API key** — paid ChatGPT plan, not Free) | your host can't draw |
| **Huge context** | Gemini (1M-token window) | a file/repo won't fit your host's context |
| **Fresh knowledge** | Gemini (Google-Search grounding) · Grok (live web/X) ⚗️ | beat a stale cutoff: *"what's the current API of `<lib>`?"* |
| **Vision** | Gemini (`images=[…]`) ⚗️ | analyse a screenshot or diagram |
| **A free second opinion** | Gemini (free daily tier) · opencode · Ollama (local, $0) | a $0 cross-check |
| **Generated files** | any build lane → artifact-return | get a chart / PDF / diagram back **by path** |
| **Video** ⚗️ | Grok (Imagine) — *if your installed CLI exposes it* (Veo isn't exposed by any official Gemini CLI extension) | you need a generated clip |

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png", zone="assets")   # Codex image → file by path, no API key (paid ChatGPT plan)
ask_gemini(task="find the bug across ./src — read the files you need", cwd="path/to/repo")         # 1M-token context
ask_gemini(task="what's the current recommended API for <lib>? check the latest docs")            # fresh knowledge (Search grounding)
ask_gemini(task="what's wrong in this UI?", images=["screenshot.png"])                             # vision (experimental)
```

⚗️ = experimental / depends on the installed CLI's current build (e.g. Grok Build is beta) — verify with `doctor --deep`.

### Never stop working when you hit a limit
When your main subscription caps out mid-task. `ask_cascade` falls through to another lane you already
pay for, skipping any lane that's cooled down after a quota/auth/timeout error.

```
ask_cascade(task="finish wiring this endpoint")   # cheapest→strongest; a cooled-down lane is skipped
ask_best(task="…", mode="deep")                   # let the router pick the most suitable available lane
```

### Offload the grunt work — in parallel, and cheap
When the work is laborious but not hard (refactors, migrations, test coverage). Fan it out, journaled
so a server restart resumes instead of restarting; delegate a build and keep working.

```
batch_run(tasks=[...], dry_run=true)                       # cost envelope first — nothing is spawned
batch_run(tasks=[...], max_calls=20, max_credits=2.0)      # then run under a hard budget (resumable)
ask_build(lane="opencode", task="add the landing page", zone="frontend", mode="direct", async=true)   # delegate, keep building
job_tail(job_id="…")  ·  build_steer(job_id="…", instruction="use Tailwind, not inline CSS")
```

### Break self-confirmation — the 2026 problem one vendor can't solve
When you need to *trust* a result. A model reviewing its own work (or a sibling's) just confirms its
own blind spots. cli-bridge puts a **different model family** in the reviewer's seat.

```
workflow(preset="jury", task="is this migration safe?", author_lane="gpt")            # cross-family vote, fail-closed
workflow(preset="verify_repair", task="add retry with backoff",
         builder_lane="gpt", verifier_lane="gemini")                                   # A builds, B reviews, loop to green
security_review(base="origin/main")   ·   review_diff(base="origin/main")              # OWASP, severity-ranked
```

### Get a real second opinion
When you've reached a conclusion and want it pressure-tested, or several models side by side.

```
challenge(task="I'm dropping the cache layer — here's why: …")                         # one skeptic attacks it
consensus(task="which migration strategy is safest here?")                             # N answer, peer-rank the best
workflow(preset="fanout_compare", task="fix this failing test", lanes=["gpt","gemini","opencode"])
```

---

## The toolbox

~30 tools, grouped by intent — the headline ones:

- **Consult** (read-only): `ask_<lane>` (one model), `ask_all` (every free lane in parallel + a disagreement score), `ask_cascade` (resilient fall-through), `ask_best` (router), `consensus`, `challenge`.
- **Build** (opt-in write): `ask_build` — `mode=isolated`→diff · `mode=direct`→zone-guarded · `async`→steerable, behind an executable Definition-of-Done gate.
- **Review & verify**: `review_diff`, `security_review`, `debate`, and `workflow(preset=…)` — `jury` (cross-family k-of-N vote, fail-closed), `verify_repair`, `fanout_compare`, …
- **Orchestrate & operate**: `batch_run` (durable, budget-capped fan-out), plus `usage_report`, `rate_lane`, `lane_stats`, `set_lane_cost`, `doctor`.

**Full reference — every tool, every flag: [`docs/TOOLS.md`](docs/TOOLS.md)** (or `cli-bridge --help`). Run `CLI_BRIDGE_LEAN=1` for a curated ~12-tool surface.

There's also a **human CLI** — `cli-bridge doctor|ask|build|review-diff|eval|…` — the same engine from your terminal or CI (`--json` everywhere); `cli-bridge build <lane> "<task>"` returns a reviewable **diff** without touching your repo (`--apply` to land it as unstaged changes).

---

## What you actually get when you combine them

One assistant whose ceiling on **every axis is the ecosystem's best** — not the tool you opened this
morning: code with the strongest model, read ~1M tokens when yours is too short, answer with fresh
knowledge past a stale cutoff, generate images/video, see screenshots, and fall back to a free/local
lane when you're capped — spread across the subscriptions you already pay for.

The emergent property **no single CLI has: true cross-vendor control** — a *different vendor* in the
reviewer's seat. Same-family subagents (Claude Code's, Grok's) can only self-confirm.

The honest seam: this unites **capabilities, not mind** — stateless spawns (no shared memory), spawn
latency/cost, uneven quality, and the host always drives. It's **orchestration, not fusion**: you
conduct specialists, you don't get one brain with every power.

→ Per-CLI strengths & limits (dated, churns fast): **[docs/COMPARISON.md](docs/COMPARISON.md)**.

## Why cli-bridge (and not another "call other models" MCP)

- 🛡️ **Ban-safe by design.** It spawns each model's **official CLI**, exactly as you'd run it by hand —
  no OAuth-token extraction, no API-key reuse. Each CLI handles its own auth and billing.
- 💸 **Cost-safe defaults you tune to your plan.** Out of the box `ask_all` / `ask_cascade` build a
  *free* council and never touch paid quota unless you ask. Each lane ships a tier sourced from the
  vendor's published plans (dated in [docs/COSTS.md](docs/COSTS.md), **never detected from your
  account**); override per lane with `CLI_BRIDGE_<LANE>_COST=free|limited|paid`. Two caps are
  **enforced at spawn** — `CLI_BRIDGE_<LANE>_DAILY_LIMIT` (runs/day, any lane) and
  `CLI_BRIDGE_DAILY_CREDIT_CAP` — full model in [docs/BUDGET.md](docs/BUDGET.md).
- 🔌 **Works from any host.** Claude Code, Codex, opencode, Cursor, VS Code (Cline/Continue), Zed —
  anything that speaks MCP over stdio. The host's own lane is kept out of fan-out; hide it with
  `CLI_BRIDGE_HIDE_HOST=1`. Even a **local model can be the host** — see
  [`examples/local-first-host.md`](examples/local-first-host.md).
- 🧭 **The cross-vendor edge is the moat.** Independent verification means a *different vendor* in the
  reviewer's seat — the scarce thing as AI writes a larger share of code, and exactly what a
  single-vendor tool can't offer.

### Side by side

How the multi-model orchestrators differ on the axes that bite later — auth model, spend control,
and what happens to your repo. (As of June 2026, read from each project's public repo/docs —
corrections welcome.)

|  | [claude-octopus](https://github.com/nyldn/claude-octopus) | [PAL / zen-mcp](https://github.com/BeehiveInnovations/zen-mcp-server) | **cli-bridge** |
|---|---|---|---|
| **How other models are reached** | hybrid: CLI spawn, OAuth-subscription reuse, or API keys | API keys (providers) + CLI spawn (`clink`) | **official CLI subprocess only** — each CLI keeps its own auth |
| **API keys needed** | optional fallback | for most providers | **never** |
| **Spend control** | session-only cost gate (`OCTOPUS_MAX_COST_USD`; no cross-session history) | none found | **enforced**: per-lane daily run limit + daily credit cap + per-invocation budget, persisted ([docs/BUDGET.md](docs/BUDGET.md)) |
| **Delegated edits** | in-place | in-place (bypass/yolo flags) | **throwaway worktree → diff** (your repo untouched), or zone-guarded direct mode |
| **Survives host restart / `/compact`** | session-scoped state | in-memory threads (TTL) | **sqlite**: conversations, jobs, fan-out journal |
| **Runtime deps** | Node 18+, npm, bash | Python + pip packages | **Python stdlib + `mcp`** |
| **Hosts** | Claude Code-first (plugin; MCP server secondary) | any MCP host | any MCP host (+ a Claude Code plugin) |

Where they're stronger, honestly: claude-octopus ships a much larger workflow surface (49 commands,
32 personas, CI reactions) and PAL has the biggest community (~11.6k★) with a polished tool set.
cli-bridge's bet is narrower: **ban-safe auth, enforced budgets, and delegation that can't wreck
your repo** — verified by its own shipped eval instead of claimed.

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

<div align="center">

<img src="https://raw.githubusercontent.com/JoaoBerne/cli-bridge-mcp/main/assets/demo.gif" width="860" alt="cli-bridge security-review demo: a committed auth bypass is caught by a cross-vendor council, merged into one severity-ranked report, $0 on free lanes">

_Real run, real-time: the Verify lever — `security-review` fans OWASP roles across several models
in parallel (claude/gpt/opencode/ollama here); they flag a committed auth bypass **blocker**, and
`usage` shows the receipts._

</div>

---

## Writing code safely: two modes

Writes are contained, two ways — **you pick** review-gated or hands-off:

- **`isolated` (default).** Edits in a throwaway git worktree and hands back a **diff**. Your working
  tree is never touched.
- **`direct`.** Writes real files, **but only inside a `zone` you declare**, behind a per-zone lock
  with a post-turn zone-violation check. You in `backend/`, a delegate in `frontend/`, concurrently —
  neither can scribble across your whole repo; undo is zone-scoped, never a global reset.

Delegate re-entry is depth-capped (`CLI_BRIDGE_MAX_DEPTH`, default 1) so a misconfigured delegate
can't fork-bomb the council.

---

## Installation (≈5 min)

**Prerequisites**

- **Python 3.10+** and **[`uv`](https://docs.astral.sh/uv/)** (`uvx` ships with it):
  `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) · `winget install astral-sh.uv` (Windows).
- **At least one AI CLI installed and logged in** — that's what cli-bridge borrows. Have any of:
  Claude Code, Codex, Gemini CLI, opencode, Ollama (local, $0). You consult only the lanes you already have.

**1. Check what cli-bridge can see** (no install — `uvx` fetches, runs, discards):

```bash
uvx --from cli-bridge-mcp cli-bridge doctor
```

`doctor` lists which CLIs are detected, their resolved paths, and cost tiers. `doctor --deep`
validates each lane against its own `--help`.

**2. Add it to your MCP host.** cli-bridge is an MCP server — it runs *inside* your assistant, not by
hand. Point the host at the same command:

- **Claude Code — as a plugin** (one-time, adds `/cli-bridge:council`, `/cli-bridge:review`,
  `/cli-bridge:security`, `/cli-bridge:build`, `/cli-bridge:setup` and wires the MCP server):
  ```bash
  claude plugin marketplace add JoaoBerne/cli-bridge-mcp
  claude plugin install cli-bridge@cli-bridge-mcp
  ```
- **Claude Code — MCP only** (no slash commands):
  ```bash
  claude mcp add cli-bridge -- uvx cli-bridge-mcp
  ```
- **Desktop apps — Claude Desktop, Hermes Desktop, …** cli-bridge is a plain stdio MCP
  server, so any desktop MCP client runs it:
  - **Claude Desktop**: Settings → Developer → Edit Config (`claude_desktop_config.json`),
    add the `mcpServers` block below, restart the app.
  - **Hermes Desktop** (Nous Research): Settings → MCP servers → Add → command `uvx`,
    args `cli-bridge-mcp`.
  - GUI apps launch servers with a **minimal PATH** — cli-bridge compensates by also
    searching the usual install dirs (`/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin`,
    `~/.npm-global/bin`, …) for your CLIs. If a lane still shows "NOT on PATH" in `doctor`,
    point it directly: `CLI_BRIDGE_<LANE>_BIN=/full/path/to/cli` in the server's `env`.
- **Any other host** (Codex, Cursor, VS Code, Zed, …) — add to its MCP config
  (`~/.claude.json`, `.mcp.json`, or the host's equivalent):
  ```json
  {
    "mcpServers": {
      "cli-bridge": {
        "command": "uvx",
        "args": ["cli-bridge-mcp"]
      }
    }
  }
  ```
  Full example with env vars: [`examples/mcp.example.json`](examples/mcp.example.json).
  Per-host config paths (Cursor, VS Code, Cline, Windsurf, Continue, Zed, Visual Studio, Neovim,
  Xcode) and how to make your agent consult it on its own: [`docs/HOSTS.md`](docs/HOSTS.md).

> Note: `cli-bridge-mcp` (the MCP server) is the host entry point; `cli-bridge` (no `-mcp`) is the
> human terminal CLI you ran for `doctor` in step 1.

**3. Use it.** Restart/reload your host and ask it to consult a lane — e.g. *"use cli-bridge to get a
second opinion from gpt"* or *"ask gemini to read ./src and find the bug"*.

### Lanes

**Built-in:** Claude Code, Codex, Gemini (+ Antigravity `agy`), Mistral (Vibe), opencode, **Ollama
(local models, $0, offline)**, Qwen Code, Copilot, Grok.

**Local runtimes** beyond Ollama — **LM Studio · MLX · llama.cpp** — ship as zero-code recipes:
point `CLI_BRIDGE_LANES_FILE` at [`examples/lmstudio.lane.json`](examples/lmstudio.lane.json),
[`mlx.lane.json`](examples/mlx.lane.json), or [`llamacpp.lane.json`](examples/llamacpp.lane.json).
(Several local runtimes of the *same* open weights give correlated answers — real council diversity
comes from distinct vendors, not a second local runtime.)

**Community lanes** (`examples/community-lanes.json`, experimental + `limited` until you declare their
cost): Aider, Goose, Plandex, Amp, Crush, Amazon Q Developer CLI, Droid.

**Anything else is ~3 lines of JSON.** Add a custom lane, or wrap any OpenAI-compatible endpoint by
spawning `curl` (key kept inside curl, never in argv). See [`examples/`](examples/) for recipes.

---

## The honest part

"More models = better" is *fragile* — big models share training data, so their errors correlate. We
measured our own central claim (`cli-bridge eval`, no LLM judge): a diverse council did **not** catch
more bugs than one strong model — it cut the false alarms **~2×**. Same catch rate, far less noise —
which is exactly what keeps a reviewer trustworthy instead of muted. **Precision is the product, not
recall.** The harness ships, so you can confirm it on *your* CLIs — numbers either way in
[docs/BENCHMARKS.md](docs/BENCHMARKS.md).

---

## Known limitations

- **Ban-safe = no token/key extraction**, not a blanket guarantee — non-interactive use of a
  provider's CLI isn't formally sanctioned everywhere and can change. Use your own accounts within
  their terms.
- **Async jobs are in-process** — a server restart marks running jobs `interrupted`. `batch_run` /
  `workflow` are the exception: they journal each task and resume via `resume_id`.
- **The injection guard is heuristic** — it catches high-signal patterns, not everything; treat
  delegate output as data, not instructions.
- **Token/credit figures are estimates** (chars/4 + your `CREDITS_PER_1K`), never exact.
- **Cost tiers are sourced defaults, not detection** — vendor-plan facts are dated; `doctor` warns
  when the snapshot is stale.
- **Experimental** (`qwen`, `copilot`, `grok`, community lanes, Gemini `images=`): flags aren't
  verified live — `doctor --deep` checks them against each CLI's `--help` on your machine.

---

## Roadmap

See [`CHANGELOG.md`](CHANGELOG.md) for shipped history. Currently **exploring (not shipped)**: an
**independent-oracle** verify mode (a cross-family lane writes tests from the *spec*, blind to the
implementation, so the test catches the bug instead of mirroring it) and tighter **limit-aware
failover**. Big inter-agent "bus" ideas (recursive spawn, shared state, wire protocol) are positioned
honestly as a *direction*, never sold as a shipped protocol — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## References

The design choices above aren't vibes — each maps to a finding in the literature. Every entry was
checked against its source (authors + venue), because a tool that sells "honest cross-vendor
verification" should get its own citations right.

| Paper | ID | What it backs here |
|-------|----|--------------------|
| Du et al. — *Improving Factuality and Reasoning via Multiagent Debate* | [2305.14325](https://arxiv.org/abs/2305.14325) | `debate`: models critiquing each other beat one model alone |
| ReConcile — *Round-Table Conference Improves Reasoning* | [2309.13007](https://arxiv.org/abs/2309.13007) | `debate` convergence + confidence-weighted consensus |
| Mixture-of-Agents | [2406.04692](https://arxiv.org/abs/2406.04692) | layered aggregation across diverse models (and its limits) |
| Chain-of-Agents | [2406.02818](https://arxiv.org/abs/2406.02818) | role-specialized multi-agent pipelines |
| CriticGPT — *LLM Critics Help Catch LLM Bugs* | [2407.00215](https://arxiv.org/abs/2407.00215) | `review_diff` / `security_review`: an LLM critic catches bugs humans miss |
| Perez et al. — *Discovering Language Model Behaviors* (sycophancy) | [2212.09251](https://arxiv.org/abs/2212.09251) | why a same-family judge is weak → cross-vendor `jury` + peer anonymization |
| Wynn, Satija & Hadfield — *Talk Isn't Always Cheap* | [2509.05396](https://arxiv.org/abs/2509.05396) | debate failure modes → fail-closed verdicts, bounded rounds |
| CONSENSAGENT — *Consensus via Sycophancy Mitigation* (Findings of ACL 2025) | [ACL 2025](https://aclanthology.org/2025.findings-acl.1141/) | sycophancy in consensus → "earn their seat" / anonymized peers |
| Maryanskyy — *When Agents Disagree: The Selection Bottleneck* | [2603.20324](https://arxiv.org/abs/2603.20324) | `consensus`: **selection > synthesis** (the deterministic peer-vote default) |

> **A citation hygiene note.** *Talk Isn't Always Cheap* (2509.05396) is **Wynn, Satija & Hadfield** —
> a popular council framework miscites it as "Xiong et al." We double-check attributions before
> repeating them, and flag it because honesty is the whole pitch.

## Development

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests; no real CLI or network needed
```

## License

Apache 2.0

---

<div align="center">

<img src="https://raw.githubusercontent.com/JoaoBerne/cli-bridge-mcp/main/assets/mark.gif" width="84" alt="cli-bridge">

<sub>one side · bridged to a council</sub>

</div>
