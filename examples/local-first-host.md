# Local-first host: a local model as the brain, cloud power on tap

For a dev who codes with **local models** (private, $0, offline) but occasionally needs more
horsepower than the local model has. The local model stays the orchestrator; cli-bridge lets it
"phone a friend" — escalate one hard task to a strong cloud lane — without giving up the local-first
default.

## The shape

```
opencode (brain = a LOCAL ollama model)  ──MCP──▶  cli-bridge  ──▶  [ ask_gpt | ask_gemini | … ]
        ↑ you code locally, private, $0                          ↑ cloud strength, only when asked
```

Why opencode is the host (not bare `ollama`): orchestrating MCP tools requires an **MCP client**.
`ollama run` is prompt→completion — it can't call tools. opencode *is* an MCP client **and** can run
a local ollama model as its backend, so it's the natural local-first brain. (The `ollama` lane
inside cli-bridge is a *leaf* — it answers/builds; it doesn't orchestrate.)

## Prerequisites

- ollama running with a **tool-capable** model pulled (`ollama pull qwen3.5` / `gemma4` etc.).
  ⚠️ A tiny model (e.g. `:0.8b`) won't reliably emit MCP tool calls — give the brain a real one.
- opencode installed; cli-bridge runnable (`uvx --from cli-bridge-mcp cli-bridge`).
- At least one cloud lane logged in (e.g. `gemini`/`agy`, `codex`) so there's something to escalate to.

## 1. Point opencode at a local ollama model (the brain)

In `~/.config/opencode/opencode.json` — ollama exposes an OpenAI-compatible endpoint, so the stock
`@ai-sdk/openai-compatible` provider works:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "ollama": {
      "name": "Ollama",
      "npm": "@ai-sdk/openai-compatible",
      "options": { "baseURL": "http://127.0.0.1:11434/v1" },
      "models": { "qwen3.5": { "name": "qwen3.5" } }
    }
  }
}
```

## 2. Register cli-bridge as a local MCP server

Same file, add an `mcp` block (any MCP client uses an equivalent — see the main README):

```jsonc
{
  "mcp": {
    "cli-bridge": {
      "type": "local",
      "command": ["uvx", "cli-bridge-mcp"],
      "enabled": true
    }
  }
}
```

## 3. Run local, escalate on demand

Start opencode with the local model selected as the active model. cli-bridge's tools now appear to
your local brain. It hides opencode's *own* lane automatically (you're the host), and exposes the
rest. Useful patterns:

- **`ask_cascade`** — cheapest→strongest with auto-fallback. Put a local/cheap lane first; it only
  reaches cloud when the local attempt fails or hits a wall.
- **`ask_best mode=deep`** — let the router pick a strong lane for a genuinely hard task.
- **confidence-escalate** (opt-in) — escalate to a stronger lane *only when the local answer is
  low-confidence*, so the common case stays 100% local.

The `ollama` lane is still exposed too (redundant with your brain); hide it if you want a clean tool
list: `CLI_BRIDGE_OLLAMA_ENABLED=false`.

## What stays true

- **Private by default.** Nothing leaves your machine until *you* call a cloud lane. The local brain
  + local lanes are $0 and offline.
- **Ban-safe.** cli-bridge spawns the official cloud CLIs you're already logged into — no API keys,
  no token extraction — same as every other host.
- **Decorrelation note.** Escalating to a *different vendor* (cloud) is what buys you a real second
  opinion; a second *local runtime of the same open weights* (lms/mlx/llama.cpp) would just agree
  with itself. See the local lane recipes in this folder.
