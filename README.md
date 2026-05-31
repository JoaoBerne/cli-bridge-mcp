# cli-bridge

**Your AI assistant, but it can phone a friend.**

`cli-bridge` is a [Model Context Protocol](https://modelcontextprotocol.io) server that lets
whatever AI you're already talking to — Claude Code, Codex, Gemini CLI, opencode, anything that
speaks MCP — **consult a council of other AI CLIs** and bring back their answers.

Stuck on a gnarly bug? Have Claude ask GPT *and* Gemini in parallel and compare. Need a 1M-token
read of a huge file? Hand it to Gemini. Want a cheap second opinion? Fire it at a free model.
One question, every model, side by side — without leaving your terminal.

```
You → Claude:  "ask the council whether this auth logic is safe"
Claude → cli-bridge → [ Gemini ] [ GPT ] [ Mistral ] [ Qwen ] … in parallel
            ← three independent reviews, side by side
```

---

## Why this one

There are other "call other models" MCPs. Here's what makes cli-bridge different:

- 🛡️ **Ban-safe by design.** It spawns the **official CLI** of each model — exactly as you'd run
  it by hand. No OAuth-token extraction, no API-key reuse, nothing that gets accounts flagged.
  Each CLI handles its own auth and billing.
- 💸 **Free by default.** Most lanes run on subscription/free-tier logins (your ChatGPT, Gemini,
  Mistral accounts) — quota, not pay-per-token. The one paid lane (opencode credits) **defaults to
  a free model** and warns you before spending.
- 🔌 **Works from any host.** Driving Claude Code? It hides the Claude lane (no asking yourself) and
  exposes the rest. Driving Codex or opencode instead? Same deal, automatically.
- 🧩 **Add any CLI without forking.** Built-in lanes for Claude, GPT, Gemini, Mistral, Qwen, Copilot
  and opencode — and you can register **your own CLI from a JSON file**, zero code.
- 🧱 **Hardened.** Timeouts kill the whole process tree (no orphans burning quota), secrets are
  redacted from output, runaway dumps are capped, errors are classified (`quota` / `auth` / `timeout`)
  so your assistant knows what to do next.

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
what's on your `PATH`. Run the `doctor` tool any time to see what's wired up.

| Lane | CLI | Cost |
|------|-----|------|
| `ask_claude`   | [Claude Code](https://docs.claude.com/claude-code) | subscription |
| `ask_gpt`      | [OpenAI Codex](https://github.com/openai/codex) | subscription |
| `ask_gemini`   | Gemini CLI / Antigravity | free / subscription |
| `ask_mistral`  | Mistral Vibe | free tier |
| `ask_qwen`     | Qwen Code | free / subscription |
| `ask_copilot`  | GitHub Copilot CLI | subscription |
| `ask_opencode` | [opencode](https://opencode.ai) gateway (deepseek, qwen, glm, kimi…) | **credits** (free model by default) |

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
> *"Have the whole council review my diff and tell me where they disagree."*
> *"Get GPT to think hard about this race condition."* (→ `effort: high`)

---

## Tools

| Tool | What it does |
|------|--------------|
| `ask_<lane>` | Ask one model. Params: `task`, optional `model`, `effort`, `cwd`, `timeout_s`. |
| `ask_all` | Fan-out the same question to **every** available lane in parallel. Free lanes only unless `include_paid: true`. |
| `list_<lane>_models` | List the models that lane can reach (where supported). |
| `doctor` | Health check: installed CLIs, which host is detected, paid lanes, default models. |

Every lane is **read-only by default** — the delegate analyses and answers; your host applies any
edits. (The one exception is opencode's `agent: "build"`, which you opt into explicitly to let it
edit files directly.)

---

## Configuration

Everything is environment variables — no code edits.

| Variable | Effect |
|----------|--------|
| `CLI_BRIDGE_<LANE>_BIN` | Point a lane at a different binary. e.g. `CLI_BRIDGE_GEMINI_BIN=agy` to use Antigravity. |
| `CLI_BRIDGE_<LANE>_MODEL` | Default model for a lane when the caller doesn't pass one. |
| `CLI_BRIDGE_HOST` | Force the host identity (which lane to hide). Normally auto-detected from MCP. |
| `CLI_BRIDGE_LANES_FILE` | Path to a JSON file adding **your own** CLIs as lanes. |

### Add your own CLI (no fork)

Create `my-lanes.json` and point `CLI_BRIDGE_LANES_FILE` at it:

```json
[
  {
    "key": "grok",
    "display": "Grok (xAI CLI)",
    "bin": "grok",
    "ask": ["chat", "{task}"],
    "model_flag": "-m",
    "default_model": "grok-beta",
    "client_ids": ["grok-cli"],
    "note": "xAI Grok via its official CLI."
  }
]
```

You now have an `ask_grok` tool. That's it.

---

## How it works

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
              hides the host's own lane · only shows installed CLIs
              kills the whole process tree on timeout · redacts secrets
              classifies errors (quota/auth/timeout) · caps runaway output
```

No network calls of its own. No keys stored. It runs the same binaries you already trust, in your
working directory, and hands the answer back.

---

## License

MIT © JoaoBtt
