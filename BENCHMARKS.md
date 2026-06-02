# Benchmarks

These numbers are **machine- and account-specific** (your CLIs, your plans, your network), so
cli-bridge ships the *tool* to measure them rather than baked-in figures. Generate your own:

```bash
# latency p50/p95/p99 + ok-rate + est. output tokens, per free lane
cli-bridge bench --all --prompt "Reply with exactly: OK" --runs 10

# one lane, machine-readable
cli-bridge bench --lane gemini --prompt "Summarize MCP in one line" --runs 10 --json
```

The dominant cost is the **delegate CLI's own startup + model latency** (typically seconds), not
cli-bridge's overhead (~tens of ms) — see the language verdict in the design notes. Use these
numbers to pick `ask_best --mode fast` lanes and to set `CLI_BRIDGE_*_PRIORITY`.

## Example (fill in your own — `bench --all`)

| lane | ok | p50 ms | p95 ms | p99 ms | avg ms | ~out tok |
|------|----|-------:|-------:|-------:|-------:|---------:|
| gemini | 10/10 | … | … | … | … | … |
| mistral | 10/10 | … | … | … | … | … |
| opencode | 10/10 | … | … | … | … | … |

> Tip for maintainers: run on a clean machine and paste the table here before a release so users
> have a realistic baseline. Don't invent numbers — measured only.
