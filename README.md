# cli-bridge

![license](https://img.shields.io/badge/license-MIT-green)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![tests](https://img.shields.io/badge/tests-pytest-brightgreen)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**Your AI assistant, but it can phone a friend.**

`cli-bridge` is a [Model Context Protocol](https://modelcontextprotocol.io) server that lets
whatever AI you're already talking to — Claude Code, Codex, Gemini CLI, opencode, anything that
speaks MCP — **consult a council of other AI CLIs** and bring back their answers.

Stuck on a gnarly bug? Have your assistant ask GPT *and* Gemini in parallel and compare. Need a
1M-token read of a huge file? Hand it to Gemini. Want a cheap second opinion? Fire it at a free
model. One question, every model, side by side — without leaving your terminal.

```
You → Claude:  "ask the council whether this auth logic is safe"
Claude → cli-bridge → [ Gemini ] [ GPT ] [ Mistral ] [ Qwen ] … in parallel
            ← three independent reviews + a synthesis of where they agree & disagree
```

---

## Why this one

There are other "call other models" MCPs. Here's what makes cli-bridge different:

- 🛡️ **Ban-safe by design.** It spawns each model's **official CLI** — exactly as you'd run it by
  hand. No OAuth-token extraction, no API-key reuse, nothing that gets accounts flagged. Each CLI
  handles its own auth and billing.
- 💸 **Sensible cost defaults, then *you* tune to your plan.** Out of the box `ask_all` builds a
  free council (Gemini + Mistral + opencode) and never touches subscription quota (Claude, GPT) or
  paid credits unless you ask. Each lane ships a realistic tier
  (`CLI_BRIDGE_<LANE>_COST=free|limited|paid`) that you override per your own subscriptions — on a
  big plan, mark them all `free`, or set `CLI_BRIDGE_PROFILE=max`.
- 🔌 **Works from any host.** Driving Claude Code? It hides the Claude lane (no asking yourself)
  and exposes the rest. Driving Codex or opencode instead? Same deal, detected automatically from
  the MCP handshake.
- 🧩 **Add any CLI — or your own API — without forking.** Built-in lanes for Claude, GPT, Gemini,
  Mistral, Qwen, Copilot and opencode. Register **your own CLI from a JSON file**, or wrap **your
  own API** by spawning `curl`. Zero code.
- 🧠 **Council synthesis.** `ask_all` can have a free model summarize where the others *agree* and
  *disagree* — turn three opinions into one decision.
- 🪶 **Subagent-style returns.** A delegate works in its own context and hands back a digest; huge
  outputs spill to a file and only a preview comes back, so your assistant's context stays lean.
- 🔁 **Automatic fallback.** `ask_cascade` tries lanes cheapest→strongest and moves on when
  one hits quota/auth/timeout — so a dead lane degrades gracefully instead of failing you.
- 🩺 **Self-aware.** Local telemetry tracks each lane's health and puts a lane in cooldown
  after repeated quota/auth/timeout failures, so `ask_all`/`ask_cascade` route around it.
- 🧱 **Hardened.** Timeouts kill the whole process tree (no orphans burning quota), host
  cancellation kills the delegate, secrets are redacted, errors are classified
  (`quota` / `auth` / `timeout`) so your assistant knows what to do next. Works on
  macOS / Linux / Windows.

### vs. other multi-model MCPs

| | cli-bridge | API-key gateways | token-reuse bridges |
|---|:---:|:---:|:---:|
| Ban-safe (spawns official CLI) | ✅ | ➖ (your keys) | ❌ (ToS risk) |
| No API keys to manage | ✅ | ❌ | ✅ |
| Uses your existing subscriptions | ✅ | ❌ | ✅ |
| Per-plan cost tiers + cooldown | ✅ | ➖ | ❌ |
| Automatic fallback (cascade) | ✅ | some | ❌ |
| Add any CLI / your own API, no fork | ✅ | ➖ | ❌ |
| Self-hides the calling host | ✅ | n/a | ➖ |

---

## Quick start

### 1. Install

```bash
# zero-install run (recommended)
uvx cli-bridge-mcp

# or install it
uv tool install cli-bridge-mcp     # or: pipx install cli-bridge-mcp
```

You only get a lane for a CLI you've **already installed and logged into**. cli-bridge auto-detects
what's on your `PATH`. Run the `doctor` tool any time to see what's wired up (`doctor deep` even
live-checks each login).

| Lane | CLI | Cost (typical) |
|------|-----|------|
| `ask_claude`   | [Claude Code](https://docs.claude.com/claude-code) | subscription |
| `ask_gpt`      | [OpenAI Codex](https://github.com/openai/codex) | subscription |
| `ask_gemini`   | Gemini CLI (or `agy` / Antigravity) | free / subscription |
| `ask_mistral`  | Mistral Vibe | free tier |
| `ask_qwen` ⚗️  | Qwen Code | free / subscription |
| `ask_copilot` ⚗️ | GitHub Copilot CLI | subscription |
| `ask_opencode` | [opencode](https://opencode.ai) gateway (deepseek, qwen, glm, kimi…) | free by default; some models use credits |

⚗️ = experimental (flags not yet verified live — please report breakage).

### 2. Register it with your host

**Claude Code** — one command:

```bash
claude mcp add cli-bridge -- uvx cli-bridge-mcp
```

<details>
<summary><b>Codex</b> (<code>~/.codex/config.toml</code>)</summary>

```toml
[mcp_servers.cli-bridge]
command = "uvx"
args = ["cli-bridge-mcp"]
```
</details>

<details>
<summary><b>opencode</b> / <b>Gemini CLI</b> / other MCP clients</summary>

Point your client's MCP config at the command `uvx cli-bridge-mcp` over stdio. Same everywhere.
</details>

### 3. Use it

Just talk to your assistant:

> *"Ask Gemini for a second opinion on this function."*
> *"Have the whole council review my diff and synthesize where they disagree."*
> *"Get GPT to think hard about this race condition."* (→ `effort: high`)

---

## Tools

| Tool | What it does |
|------|--------------|
| `ask_<lane>` | Ask one model. Params: `task`, optional `model`, `effort`, `agent`, `cwd`, `timeout_s`. |
| `ask_all` | Fan-out the same question to every free, non-limited lane in parallel. `synthesize: true` adds an agreement/disagreement summary. `include_paid: true` to also query limited/paid lanes. |
| `ask_cascade` | Ask one model **with automatic fallback** — tries lanes cheapest→strongest, skipping cooled ones, moving on at quota/auth/timeout. Returns the first success. |
| `route_plan` | Show the order `ask_cascade` would try, given your profile + current cooldowns (read-only, runs nothing). |
| `list_<lane>_models` | List the models that lane can reach (where supported). |
| `doctor` | Health check: installed CLIs, detected host, cost/quota stance, cooldowns, defaults. `deep: true` live-probes each free, non-limited lane's auth. |
| `usage_report` | Local-only stats: total runs, per-lane counts/success/latency, recent calls. |
| `lane_stats` | Per-lane health: runs, failures, consecutive failures/timeouts, active cooldown. |
| `reset_lane_state` | Clear a lane's cooldown/failure counters (after re-login or quota reset). |
| `setup` | Walk the user through configuring cost preferences to their own subscriptions. |

Every lane is **read-only by default** — the delegate analyses and answers; your host applies any
edits. The one exception is opencode's `agent: "build"`, which you opt into explicitly to let it
edit files directly (and it's annotated non-read-only accordingly).

For opencode, an empty `model` asks `opencode models` for the current `opencode/*-free` model list
and uses a free Zen model. If that lookup fails, cli-bridge falls back to
`opencode/deepseek-v4-flash-free`. Set `CLI_BRIDGE_OPENCODE_MODEL` to pin a different default.

`ask_all` keeps per-lane calls short (45s default, 60s max) so the MCP host gets a response before
its own tool-call deadline. For a slow/deep answer, call that lane directly with a longer
`timeout_s`.

---

## Configuration

Everything is environment variables — no code edits. Tune it to **your** subscriptions:

| Variable | Effect |
|----------|--------|
| `CLI_BRIDGE_<LANE>_COST` | `free`, `limited`, or `paid`. `free` joins `ask_all`; `limited` is quota-sensitive and skipped by broad fan-out; `paid` spends money/credits and is skipped by default. |
| `CLI_BRIDGE_<LANE>_ENABLED` | `false` to hide a lane even if its CLI is installed. |
| `CLI_BRIDGE_<LANE>_BIN` | Point a lane at a different binary (e.g. `CLI_BRIDGE_GEMINI_BIN=agy`). |
| `CLI_BRIDGE_<LANE>_MODEL` | Default model for a lane when the caller doesn't pass one. |
| `CLI_BRIDGE_PROFILE` | `saver`, `balanced`, or `max`. `max` includes limited/paid lanes in `ask_all` unless the caller overrides `include_paid`. |
| `CLI_BRIDGE_HOST` | Force the host identity (which lane to hide). Normally auto-detected. |
| `CLI_BRIDGE_LANES_FILE` | Path to a JSON file adding **your own** CLIs/APIs as lanes. |
| `CLI_BRIDGE_<LANE>_PRIORITY` | Lower runs earlier in `ask_cascade` (default 50). Pin your preferred order. |
| `CLI_BRIDGE_INLINE_MAX_CHARS` | Above this, an answer spills to a file instead of flooding context (default 12000). |
| `CLI_BRIDGE_TELEMETRY` | `off` to disable the local run log / cooldown tracking (default on, machine-local only). |
| `CLI_BRIDGE_STATE_DB` | Path to the local sqlite state DB (default `~/.local/share/cli-bridge/state.sqlite`). |
| `CLI_BRIDGE_STORE_TRANSCRIPTS` | `true` to keep a longer task preview in telemetry (default: hash + 60-char preview only). |
| `CLI_BRIDGE_LOG` / `_LOG_FILE` | `debug`/`info` to log what ran where (default: silent). |

### Add your own CLI (no fork)

`my-lanes.json`, then `CLI_BRIDGE_LANES_FILE=/path/to/my-lanes.json`:

```json
[
  {
    "key": "grok", "display": "Grok (xAI CLI)", "bin": "grok",
    "ask": ["chat", "{task}"], "model_flag": "-m", "default_model": "grok-beta",
    "client_ids": ["grok-cli"], "note": "xAI Grok via its official CLI."
  }
]
```

You now have an `ask_grok` tool.

### Bring your own API (no CLI needed)

Wrap any OpenAI-compatible endpoint by spawning `curl`. Your key stays in an env var, never in the
file. `{task_json}` is the prompt, JSON-escaped:

```json
[
  {
    "key": "myapi", "display": "My API", "bin": "curl", "default_model": "gpt-4o-mini",
    "paid": true,
    "ask": [
      "-sS", "https://api.openai.com/v1/chat/completions",
      "-H", "Authorization: Bearer ${MY_API_KEY}",
      "-d", "{\"model\":\"{model}\",\"messages\":[{\"role\":\"user\",\"content\":\"{task_json}\"}]}"
    ]
  }
]
```

(See `examples/` for both, ready to copy.)

---

## How it works

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
              hides the host's own lane · only shows installed, enabled CLIs
              kills the whole process tree on timeout / cancellation
              redacts secrets · classifies errors · spills huge output to a file
```

No network calls of its own. No keys stored. It runs the same binaries you already trust, in your
working directory, and hands the answer back.

### Limitation

If your **host** runs the MCP server inside a strict sandbox (e.g. a read-only filesystem / no
network), the delegate CLIs it spawns inherit that sandbox and may fail to reach their providers.
In a normal terminal session this isn't an issue. cli-bridge surfaces the failure as an `auth` or
`failed` error rather than hanging.

---

## Development

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests
```

## License

MIT
