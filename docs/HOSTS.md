# Hosts — where cli-bridge runs, and how to make your agent use it

cli-bridge is a **standard stdio MCP server**. It runs inside *any* host that speaks MCP — there
is nothing host-specific to install. The same server block works everywhere:

```json
{ "mcpServers": { "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } } }
```

## Where each host keeps its MCP config

Drop the block above into your host's MCP config. The exact location is the only thing that
differs — see each host's own MCP docs for the authoritative path and UI.

| Host | Typical config location | Host MCP docs |
| --- | --- | --- |
| **Claude Code** | `claude mcp add cli-bridge -- uvx cli-bridge-mcp` (or the plugin) | [docs](https://docs.claude.com/en/docs/claude-code/mcp) |
| **Cursor** | `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global) | [docs](https://docs.cursor.com/context/model-context-protocol) |
| **VS Code** (Copilot agent mode) | `.vscode/mcp.json`, or *MCP: Add Server* | [docs](https://code.visualstudio.com/docs/copilot/chat/mcp-servers) |
| **Cline** | `cline_mcp_settings.json` (Cline → MCP Servers) | [docs](https://docs.cline.bot/mcp/configuring-mcp-servers) |
| **Windsurf** | `~/.codeium/windsurf/mcp_config.json` (Cascade) | [docs](https://docs.windsurf.com/windsurf/cascade/mcp) |
| **Continue.dev** | `~/.continue/config.yaml` → `mcpServers` | [docs](https://docs.continue.dev/customize/deep-dives/mcp) |
| **Zed** | `settings.json` → `context_servers` | [docs](https://zed.dev/docs/ai/mcp) |
| **Visual Studio 2026** | `.mcp.json` (solution) — agent mode required | [docs](https://learn.microsoft.com/en-us/visualstudio/ide/mcp-servers) |
| **Neovim** | via a plugin (mcphub.nvim, avante.nvim, codecompanion.nvim), or just run the human `cli-bridge` CLI in `:terminal` | plugin-specific |
| **Xcode 26.3** | indirect — see note | [docs](https://developer.apple.com/documentation/xcode) |

A full block with env vars (cost profile, per-lane caps) is in
[`examples/mcp.example.json`](../examples/mcp.example.json).

### Note on Xcode 26.3

Xcode gained MCP in 26.3, but **the other way around**: it exposes *itself* as an MCP server
(the `mcpbridge` binary — build, test, RenderPreview) so external agents can drive Xcode. Its
built-in assistant does not (yet) consume external MCP servers like cli-bridge. So the path is to
**drive Xcode from Claude Code or Cursor**, where cli-bridge already lives — the two coexist in the
same agent.

## Make your agent consult it on its own (optional)

cli-bridge is most useful when the host *decides* to consult it. The host already reads cli-bridge's
tool descriptions (which lead with *when* to delegate), but you can make it proactive by adding a
rule to your host's instructions file. Paste this:

> You have the **cli-bridge** MCP server — a council of other AI CLIs. Consult it proactively when:
> - you're about to ship risky code → `security_review` / `review_diff`
> - you're stuck or hitting a dead-end → ask a different model (`ask_best`, `ask_cascade`)
> - it's a high-stakes decision → `jury` / `debate`
> - a task fits another model's strength (huge context → Gemini, image generation → GPT/Codex)
>
> Do **not** convene the council for trivial edits or things you're already sure of.

Where the instructions file lives, per host:

| Host | Instructions / rules file |
| --- | --- |
| Claude Code | `CLAUDE.md` (project) or `~/.claude/CLAUDE.md` |
| Cursor | `.cursor/rules/*.mdc` |
| GitHub Copilot (VS Code / Visual Studio) | `.github/copilot-instructions.md` |
| Cline | Custom Instructions (settings) |
| Continue.dev | rules in `~/.continue` |
| Windsurf | `.windsurf/rules` or Cascade Memories |

### Keep autonomous use safe (cost)

An agent that delegates on its own can spend quota/credits. cli-bridge is safe-by-default **if you
set a cost profile**:

- `profile: saver` — excludes paid/limited lanes from any fan-out (only free lanes run unprompted).
- `CLI_BRIDGE_<LANE>_DAILY_LIMIT=<n>` — hard cap on runs/day for any lane, enforced at spawn.
- `CLI_BRIDGE_DAILY_CREDIT_CAP` — hard ceiling on estimated paid spend.

See [`docs/BUDGET.md`](BUDGET.md) for the full model. With a profile set, hands-off delegation
can't run up a bill.
