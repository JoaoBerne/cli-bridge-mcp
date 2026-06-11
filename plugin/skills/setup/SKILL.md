---
name: setup
description: First-run cli-bridge onboarding — see which AI CLIs are installed, set the cost profile and spend caps, and learn what the council can do.
---

# Setup — onboarding walkthrough

1. Call the `doctor` MCP tool (server `cli-bridge`) and show the user what it
   found: which CLIs are installed, each lane's cost tier and its source, any
   warnings (unenforceable cap, sunset countdown, cost mismatch).
2. Call the `setup` tool and follow its guidance: ask the user ONE question about
   how they pay for their CLIs (flat subscription / metered / mix), then record
   the answers with `set_lane_cost(lane, cost, note)` — it persists.
3. Offer the two enforced caps (docs/BUDGET.md in the repo explains the model):
   - `CLI_BRIDGE_<LANE>_DAILY_LIMIT` — max runs/day, exact, works for any lane.
   - `CLI_BRIDGE_DAILY_CREDIT_CAP` — estimated spend ceiling (needs per-lane
     `CREDITS_PER_1K` rates; `doctor` flags when it can't enforce).
4. No CLIs installed yet? Tell the user about `CLI_BRIDGE_MOCK=1` to explore every
   tool with canned answers before installing anything.
