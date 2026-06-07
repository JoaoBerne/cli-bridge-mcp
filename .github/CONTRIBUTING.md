# Contributing to cli-bridge

Thanks for helping out. cli-bridge aims to stay small, dependency-light, and predictable, so a
few rules keep it that way.

## Setup

```bash
uv venv && uv pip install -e . pytest pytest-asyncio ruff
CLI_BRIDGE_STATE_DB=/tmp/t.sqlite pytest -q   # keep tests off your real state db
ruff check src/ tests/
```

No real AI CLI or network is needed to develop or test — lanes are faked with `echo`/`false`
and the state DB is a temp sqlite.

## Ground rules

- **Stdlib + `mcp` only.** No new runtime dependencies. (Dev tools like `pytest`/`ruff` are fine.)
- **Keep `server.py` thin.** Business logic lives in `lanes`/`runner`/`router`/`workflows`/
  `findings`/`telemetry`. The server routes; it doesn't decide.
- **Every change ships a test**, and `pytest -q` + `ruff check` must stay green. Tests must not
  require a real CLI or network.
- **Portable**: macOS / Linux / Windows. No POSIX-only calls without a Windows branch
  (see `runner._kill_tree`).
- **Telemetry is best-effort** — it must NEVER raise into a delegation path.
- **Cost safety**: a missing/empty model must never resolve to a paid model.
- **Surgical diffs.** Match the existing style; don't reformat unrelated code.

## Adding a lane (a new CLI)

You usually don't need to fork: point `CLI_BRIDGE_LANES_FILE` at a JSON file
(see `examples/lanes.example.json`), or wrap an HTTP API with `curl`
(`examples/byo-api-lane.json`). To add a built-in lane, append a `LaneSpec` in `lanes.py` with
its argv builder and capabilities, and ship a test. See `docs/ARCHITECTURE.md` → "Extending it".

## Adding a workflow

Add a function in `workflows.py` taking `(targets, args, run_lane)`, then register a tool +
dispatch in `server.py` (and a prompt in `_PROMPTS` if it deserves a slash command). Reuse the
injected `run_lane` so it's testable with fakes.

## Commit / PR

- Conventional-commit-ish subjects (`feat(...)`, `fix(...)`, `docs(...)`) are appreciated.
- Describe the *why*, not just the *what*. Note any new env var or tool.
- Update `CHANGELOG.md` under "Unreleased".

By contributing you agree your work is licensed under the project's MIT license.
