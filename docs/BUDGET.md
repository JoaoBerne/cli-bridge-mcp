# Budget & cost governance — the full model on one page

cli-bridge never sees your bills. Everything here is **declared by you** (or a sourced
default) and **estimated locally**. This page is the single reference for how the pieces
fit; `doctor` shows your current merged state.

## The three layers

| Layer | What it answers | Where it lives |
|---|---|---|
| **Cost tiers** | "Does this lane cost me anything?" (`free` / `limited` / `paid`) | per lane: `CLI_BRIDGE_<LANE>_COST` |
| **Profile** | "How adventurous should fan-out be by default?" (`saver` / `balanced` / `max`) | `CLI_BRIDGE_PROFILE` |
| **Caps** | "Hard stop, no matter what" | `CLI_BRIDGE_<LANE>_DAILY_LIMIT`, `CLI_BRIDGE_DAILY_CREDIT_CAP` |

Tiers steer *routing* (which lanes join `ask_all`, cascade order). The profile steers the
*default* aggressiveness. Caps are the only thing that *blocks* a spawn.

## What is actually enforced, and where

Every spawn passes through one chokepoint (`budget.check_spawn`):

| Mechanism | Env var | Gates | Enforcement |
|---|---|---|---|
| Daily run limit | `CLI_BRIDGE_<LANE>_DAILY_LIMIT=<n>` | **any** lane | spawn **blocked** once the lane hit `n` runs since UTC midnight |
| Daily credit cap | `CLI_BRIDGE_DAILY_CREDIT_CAP=<n>` | paid lanes + any lane with a `CREDITS_PER_1K` rate | spawn **blocked** once today's *estimated* spend ≥ cap |
| Per-invocation budget | `max_calls` / `max_credits` args on `batch_run`/workflows | that invocation | over-budget tasks are skipped before spawning |
| Cooldowns | automatic (quota/timeout/auth errors) | the failing lane | lane excluded from fan-out, retried after backoff (max 6 h) |

Practical guidance:

- **The run limit is the cap to start with.** It needs zero math, works for every lane
  (free quotas included), and is exact — runs are counted, not estimated.
- **The credit cap needs rates.** Estimated spend is `tokens × CREDITS_PER_1K / 1000`,
  and a paid lane without `CLI_BRIDGE_<LANE>_CREDITS_PER_1K` always estimates to 0 — the
  cap can never trigger for it. `doctor` warns loudly when your cap is unenforceable.
- Both gates **fail open** if local telemetry is unavailable: a broken sqlite file must
  not take the council down. (Telemetry is on by default.)

## How spend is estimated (honestly)

```
tokens  = chars / 4            # crude, deliberately so — we never claim vendor accuracy
credits = tokens × CREDITS_PER_1K / 1000
```

There is no token extraction and no provider billing API — that's the ban-safe contract.
Pre-flight envelopes (`dry_run`) assume output ≈ 3× input as a conservative upper bound.
Every figure cli-bridge reports is labeled *estimated*; treat the credit cap as a guard
rail, not an accounting system. When you need exactness, use the run limit.

## Profile semantics (exact)

| Profile | `ask_all` / `ask_cascade` / `ask_best` fan-out | Direct `ask_<lane>` to a paid lane |
|---|---|---|
| `saver` | free lanes only — `include_paid=true` is **refused** | allowed (it's explicit) |
| `balanced` (default) | free by default; `include_paid=true` opts in | allowed |
| `max` | all lanes by default | allowed |

`saver` is a fan-out policy, not a ban: calling `ask_gpt` directly is a deliberate act,
so it goes through (the caps above still apply to it). If you want a true ban, disable
the lane: `CLI_BRIDGE_<LANE>_ENABLED=false`.

## Where settings come from (precedence)

```
host env  >  config file (~/.config/cli-bridge/config.json)  >  shipped default
```

- The config file only fills env vars that aren't already set (at server start).
- `set_lane_cost` / `cli-bridge set-cost` write the config file *and* apply immediately —
  but an env var set by your MCP host config or shell wins again at every restart
  (you get a warning when that shadowing is detected).
- `doctor` annotates every lane's tier with its source: `default`, `set by you: config
  file`, or `set by you: host env — wins over the config file`.

## Units cheat-sheet

| Setting | Unit |
|---|---|
| `CLI_BRIDGE_<LANE>_DAILY_LIMIT` | runs per UTC day (integer, exact) |
| `CLI_BRIDGE_DAILY_CREDIT_CAP` | credits per UTC day (float, estimated) |
| `CLI_BRIDGE_<LANE>_CREDITS_PER_1K` | credits per 1 000 estimated tokens |
| `max_calls` (batch/workflows) | spawns in this invocation (exact) |
| `max_credits` (batch/workflows) | estimated credits in this invocation |

"Credits" are whatever unit your plan bills in — dollars, vendor credits — cli-bridge
just compares your declared numbers; it never converts currencies.

## Recipes

```bash
# "Never more than 20 paid calls a day, period."
CLI_BRIDGE_OPENCODE_DAILY_LIMIT=20

# "Cap estimated spend at ~2 credits/day across paid lanes."
CLI_BRIDGE_DAILY_CREDIT_CAP=2
CLI_BRIDGE_OPENCODE_CREDITS_PER_1K=0.05   # required, or the cap can't see the spend

# "Free-only fan-out, but let me call GPT explicitly when I want it."
CLI_BRIDGE_PROFILE=saver

# "This machine must never spend anything."
CLI_BRIDGE_PROFILE=saver
CLI_BRIDGE_OPENCODE_ENABLED=false          # repeat for every paid lane
```

See `docs/COSTS.md` for what each vendor's plan actually includes (sourced, dated).
