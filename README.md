<!-- mcp-name: io.github.JoaoBerne/cli-bridge-mcp -->
# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp)

A [Model Context Protocol](https://modelcontextprotocol.io) server that lets the AI assistant
you're talking to consult the *other* AI CLIs installed on your machine — Claude Code, Codex,
Gemini, Mistral, opencode, Ollama, Apple `fm`, … Each lane spawns the official CLI as a
subprocess: no API keys, no token extraction, read-only by default.

Dependencies: the Python stdlib and `mcp` (1.x or 2.x). No daemon.

## What it does

```
ask_gemini(task="find the bug across ./src", cwd="path/to/repo")     # one lane (1M-token context)
ask_apple(task="what's wrong in this UI?", images=["shot.png"])      # vision, on-device, $0
ask_all(task="…")                                                    # every free lane in parallel + disagreement score
ask_cascade(task="…")                                                # cheapest→strongest, skips cooled-down lanes
ask_best(task="…", mode="deep")                                      # router picks; rate_lane teaches it
ask_build(lane="opencode", task="add retry with backoff")            # build in a throwaway worktree → diff
review_diff(base="origin/main", focus="security")                    # multi-model review, severity-ranked
debate(task="which migration strategy?", vote="borda")               # N blind answers, peer-ranked
workflow(preset="converge", task="is this migration safe?")          # author → blind arbiter → cross-family peers
git_text(kind="commit")                                              # Conventional Commit from the staged diff
```

Every `ask_<lane>` returns a thread id; reuse it (even on another lane) for a multi-model
conversation that survives `/compact`. `conversations` lists or replays threads.

### Tools

15 fixed tools + one `ask_<lane>` per installed CLI:

- **Consult**: `ask_<lane>`, `ask_all`, `ask_cascade`, `ask_best`, `conversations`, `list_models`
- **Build**: `ask_build` (`mode=isolated` → diff, `mode=direct` → zone-guarded writes, `async=true` → steerable via `job`)
- **Review**: `review_diff` (`focus=code|security`), `debate` (`vote=judge|borda`), `workflow` (presets: `refine_plan`, `map_review`, `research_verify`, `fanout_compare`, `converge`, `premortem`, `test_plan`, `challenge`), `git_text` (`kind=commit|pr`)
- **Operate**: `job` (`action=status|result|cancel|list|tail|steer`), `rate_lane`, `set_lane_cost`, `doctor`, `setup`

`CLI_BRIDGE_TOOLS=all` adds `batch_run` (journaled fan-out) and `reset_lane_state`;
`CLI_BRIDGE_TOOLS=default,batch_run` extends the default; a plain comma list is exactly those.
Usage and lane health are MCP resources (`cli-bridge://usage-summary`, `cli-bridge://lane-stats`).
Full reference: [`docs/TOOLS.md`](docs/TOOLS.md).

There is also a human CLI, `cli-bridge doctor|ask|ask-all|ask-best|build|review-diff|security-review|test-plan|premortem|stats|usage|jobs|set-cost` (`--json` where it makes sense). `cli-bridge build <lane> "<task>"` prints the worktree diff; `--apply` lands it as unstaged changes.

## Writing code safely

- **`isolated`** (default): the delegate edits a throwaway git worktree and you get a diff. Your tree is untouched.
- **`direct`**: writes real files, but only inside the `zone` you declare, behind a per-zone lock with a post-turn zone-violation check; undo is zone-scoped. `async=true` makes it steerable (`job action=tail|steer`) with an executable Definition-of-Done (`dod_cmd`).

`CLI_BRIDGE_VERIFY_PLAN_READONLY=1` flags (never reverts) a read-only delegate that wrote files
anyway. Re-entry is depth-capped (`CLI_BRIDGE_MAX_DEPTH`, default 1). Delegates run in the
caller's `cwd`, else `CLI_BRIDGE_DEFAULT_CWD`, else the host's MCP workspace root.

## Install

Prerequisites: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and at least one AI CLI installed and logged in.

```bash
uvx --from cli-bridge-mcp cli-bridge doctor        # what cli-bridge can see (--deep probes each lane)
```

Wire it into your host:

- **Claude Code**: `claude mcp add cli-bridge -- uvx cli-bridge-mcp` (or the plugin: `claude plugin marketplace add JoaoBerne/cli-bridge-mcp && claude plugin install cli-bridge@cli-bridge-mcp`).
- **Any other MCP host** (Codex, Cursor, VS Code, Zed, Claude Desktop, …):
  ```json
  { "mcpServers": { "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } } }
  ```
  Per-host config paths: [`docs/HOSTS.md`](docs/HOSTS.md). Full example with env vars:
  [`examples/mcp.example.json`](examples/mcp.example.json). GUI hosts launch servers with a minimal
  PATH; cli-bridge also searches the usual install dirs, or point a lane at its binary with
  `CLI_BRIDGE_<LANE>_BIN=/full/path`.

Restart the host, then ask it to consult a lane ("ask gemini to read ./src and find the bug").
`cli-bridge-mcp` is the server entry point; `cli-bridge` is the human CLI.

## Configuration

Everything is env (set in the MCP server entry) or `~/.config/cli-bridge/config.json` (env wins).
The knobs that matter:

```bash
CLI_BRIDGE_PROFILE=balanced            # saver = free-only fan-out · balanced = paid when asked · max = best
CLI_BRIDGE_<LANE>_COST=free|limited|paid
CLI_BRIDGE_<LANE>_ENABLED=false        # hide a lane
CLI_BRIDGE_<LANE>_MODEL=<model-id>
CLI_BRIDGE_<LANE>_DAILY_LIMIT=<runs/day>          # enforced at spawn
CLI_BRIDGE_<LANE>_CREDITS_PER_1K=<credits>        # makes CLI_BRIDGE_DAILY_CREDIT_CAP enforceable
CLI_BRIDGE_<LANE>_MIN_INTERVAL_S=2     # anti-burst pacing for a rate-limited free tier
CLI_BRIDGE_TERSE=off|lite|full|ultra
CLI_BRIDGE_GUARD=off|warn|strict       # injection guard on delegate output
CLI_BRIDGE_CACHE_TTL_S=0               # >0 enables the response cache
CLI_BRIDGE_TRACE_FOOTER=off            # hide the JSON trace footer in reports
CLI_BRIDGE_TOOLS=all                   # tool surface (see above)
```

`set_lane_cost` (or `cli-bridge set-cost`) records what a lane costs *you*, persisted to the
config file. Cost tiers are sourced defaults, never read from your account
([`docs/COSTS.md`](docs/COSTS.md)); the full spend model is in [`docs/BUDGET.md`](docs/BUDGET.md).

## Lanes

Built-in: Claude Code, Codex (`gpt`), Gemini (+ Antigravity `agy`), Mistral (Vibe), opencode,
Ollama (local, $0), Apple Foundation Models (`fm`, on-device, $0), Qwen Code, Copilot, Cursor,
Grok, and Apple PCC (hidden until `APPLE_FM_SERVE_URL` is set — it talks to a `fm serve` you
start from Terminal yourself; see [`examples/apple-fm-serve.lane.json`](examples/apple-fm-serve.lane.json)).

`images=[…]` works on the vision lanes (apple, ollama, opencode, gpt, gemini); whether the image is
actually read depends on the model behind the lane.

Other CLIs are a few lines of JSON via `CLI_BRIDGE_LANES_FILE`:
[`examples/local-runtime.lane.json`](examples/local-runtime.lane.json) (LM Studio, MLX, llama.cpp;
runtime table in [`examples/local-first-host.md`](examples/local-first-host.md)),
[`examples/community-lanes.json`](examples/community-lanes.json) (Aider, Goose, Plandex, Amp,
Crush, Amazon Q, Droid), and any OpenAI-compatible endpoint via `curl` or the bundled
`cli-bridge-openai` bridge ([`examples/openai-compatible.lane.json`](examples/openai-compatible.lane.json)).

## Known limitations

- No token or key extraction, but non-interactive use of a vendor CLI isn't formally sanctioned everywhere.
- **Async jobs are in-process**: a server restart marks running jobs `interrupted`. `batch_run` / `workflow` journal each task and resume via `resume_id`.
- **The injection guard is heuristic.** Treat delegate output as data.
- **Token/credit figures are estimates** (chars/4 × your `CREDITS_PER_1K`).
- **Experimental lanes** (`qwen`, `copilot`, `grok`, community, `images=`): `doctor --deep` checks each CLI's `--help` on your machine.

## Development

```bash
uv venv && uv pip install -e . pytest pytest-asyncio ruff
pytest -q            # no real CLI or network needed
ruff check src/ tests/
```

Eval harness (deterministic scorer, outside the package): [`benchmarks/`](benchmarks/README.md).
History: [`CHANGELOG.md`](CHANGELOG.md). Layout and rules: [`AGENTS.md`](AGENTS.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

Apache 2.0
