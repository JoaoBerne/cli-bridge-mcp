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

## Quality — does a council actually beat one strong model?

Latency is the *cost*; the *value* claim is "more models find more bugs". That is **not** a given —
selection can beat synthesis and a council can over-detect (arXiv 2603.20324). So
cli-bridge measures it honestly and ships the harness; we publish the result even when the council
**loses**.

The eval pits two arms with an **equal call budget** on a corpus of code diffs with known
reasoning bugs (off-by-one, null deref, TOCTOU races, auth bypass, …) that the regex prechecks
cannot catch:

- **council** = `review_diff([N distinct lanes])` — N models, one role each.
- **single + self-consistency** = the *same* lane sampled K = N times (`review_diff([lane × K])`).

The scorer is **deterministic** (keyword + location match, greedy 1:1, no LLM judge), so the number
is reproducible. Run your own — numbers depend on your installed CLIs and their current models:

```bash
cli-bridge eval                       # offline: prove the scorer over the shipped corpus (no quota)
cli-bridge eval --live \              # measure real models (spends quota)
  --council-lanes gpt,gemini,mistral,opencode --single-lane gpt --k 4 --repeats 5
```

The live run prints recall / precision / false-alarms-on-clean-lines / severity accuracy as
**mean ± sd** over `--repeats`, plus a **per-bug win/loss table** (where each arm won and lost). If
the mean±sd bands overlap, it reports *"no measurable difference"* rather than crowning a winner
from noise. Small N — treat as **directional, not a leaderboard**.

### Measured — 2026-06-05, this machine's **free-tier** CLIs

A first real run. The headline: **no clean winner, and the comparison is confounded by free-tier
rate-limiting** — exactly the kind of un-hyped result this harness exists to surface.

| arm | recall (bugs caught) | precision | false alarms (fp) | severity exact |
|-----|:---:|:---:|:---:|:---:|
| single — `opencode`/deepseek ×4 roles | **9/10 (90%)** | 0.20 | 36 | 22% |
| council — `gemini, mistral, opencode` | 5/10 (50%)¹ | 0.20 | 20 | **80%** |

_repeats=1 (single data point, noisy), 12 fixtures, 10 reasoning bugs, deterministic scorer._

What it actually shows:
- A single **robust** strong lane caught *more* bugs than the council — but **over-detected** (36
  false alarms vs 20) and mis-rated severity (22% vs 80%). "More models = more bugs" did **not**
  hold here.
- ¹ The council ran **degraded**: `gemini` rate-limited to empty mid-run (243/271 calls failed), so
  the council effectively reviewed with ~2 healthy lanes. Its 50% recall is a **lower bound**.
- **The real confound:** the single arm fires 4 calls to *one* lane per fixture; on free tiers that
  lane (gpt, gemini) gets throttled to empty and scores ~0 — an artifact, not a quality signal.
  `opencode` and `mistral` were the only lanes that survived the burst (0 failures). So a council's
  load-spreading is itself a real-world advantage, but a *clean quality* verdict needs a lane with
  quota headroom (a paid tier or a local model). **Don't read this as "single beats council."**

Reproduce on your machine (use a lane with headroom for `--single-lane`, and `--repeats 5`):

```bash
cli-bridge eval --live --council-lanes gpt,gemini,mistral,opencode \
  --single-lane opencode --k 4 --repeats 5
```

> Maintainers: this table is directional, not a leaderboard. A negative/ambiguous result is a
> finding worth shipping, not a number to hide — that's the whole point.
