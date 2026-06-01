# Security

cli-bridge spawns official AI CLIs as subprocesses and returns their output to your host
assistant. That puts it between two trust boundaries, so it's worth being precise about what it
defends against and what it does not.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem. Instead, open a
[GitHub security advisory](https://github.com/JoaoBtt/cli-bridge-mcp/security/advisories/new)
(or email the maintainer listed on the GitHub profile). Include repro steps and the affected
version/commit. You'll get an acknowledgement within a few days.

## Threat model

cli-bridge handles two kinds of untrusted data:

1. **Delegate output** — text produced by another model/CLI, returned to your host assistant.
   It can contain prompt-injection ("ignore previous instructions"), requests to exfiltrate
   secrets, hidden instructions in HTML comments, or shell commands disguised as guidance.
2. **The task/diff you pass in** — may itself contain secrets or hostile content.

### What cli-bridge does about it

- **Ban-safe by construction.** It only ever spawns the official CLI you already run. It never
  extracts tokens, reads credential files, or sends your API keys anywhere. (Test: `test_isolation.py`.)
- **No pollution of your CLI config.** The only things it writes are an overflow temp file, the
  local telemetry sqlite, and an optional log. Never to `~/.gemini`, `~/.codex`, etc.
- **Secret redaction.** Known secret shapes (bearer tokens, `sk-…`, `ghp_…`, `AIza…`,
  `api_key=…`) are redacted from output **before** anything is returned or logged
  (`runner.redact`). The review prechecks redact a secret's value even while flagging it.
- **Output guard.** `CLI_BRIDGE_GUARD=off|warn|strict` (default `warn`) scans delegate output for
  injection / tool-poisoning signals and, in `warn`, prepends a banner telling the host to treat
  the text as **data, not instructions**; in `strict`, it withholds the body. Runs after redaction.
- **Read-only by default.** A delegate can only edit files with an explicit `agent: build`. The
  recommended way to use write mode is **`ask_build_isolated`**, which runs the agent in a
  throwaway git worktree and returns a diff — your real repository is never modified.
- **Cost safety.** A missing/empty model never resolves to a paid model; `ask_all`/`ask_cascade`
  exclude limited/paid lanes by default.
- **Telemetry is local and minimal.** A task **hash + short preview** only (never the full
  prompt/output unless you set `CLI_BRIDGE_STORE_TRANSCRIPTS=true`), in a local sqlite DB that
  never leaves your machine. Disable with `CLI_BRIDGE_TELEMETRY=off`.

### What it does NOT protect against

- **It is not a sandbox.** A delegate CLI runs with your user's permissions. In `agent: build`
  (outside `ask_build_isolated`) it can modify files; only run write mode on code you trust.
- **The guard is heuristic.** It catches high-signal patterns, not every possible injection. In
  `warn` mode the text still reaches the host — treat delegated output as untrusted input.
- **It can't vet the models themselves.** A compromised or malicious model could emit harmful
  content; that's why output is annotated and, for writes, isolated.
- **`cwd`/path arguments are not jailed.** A delegate sees whatever directory you point it at.
- **BYO-API (curl) lanes expose the key in argv.** A custom lane that substitutes a `${ENV}` key
  into a `curl` command line puts that key in this machine's process list for the duration of the
  call (it is never logged — traces redact it, and it never leaves your machine otherwise). On a
  shared/multi-user host, prefer a provider's official CLI, or a header file (`curl -H @file`,
  `chmod 600`) so the secret stays out of argv.

## Hardening checklist for sensitive use

- Set `CLI_BRIDGE_GUARD=strict`.
- Use `ask_build_isolated` instead of raw `agent: build`.
- Keep `CLI_BRIDGE_STORE_TRANSCRIPTS` unset.
- Run from a directory that contains only what the delegate should see.
