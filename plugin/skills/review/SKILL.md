---
name: review
description: Multi-model code review of the current git diff — several AI CLIs review independently, findings are deduplicated and confidence-ranked by cross-model agreement.
---

# Review — cross-model diff review

Run a council review of the current changes.

1. Call the `review_diff` MCP tool (server `cli-bridge`) with `cwd` set to the
   repository root. Use `base` for a non-default base ref (e.g. `main`).
2. Findings come back merged across models with a confidence level
   (single/majority/consensus). Consensus findings are the ones every model saw
   independently — treat those as the priority list.
3. Present the findings to the user grouped by confidence, with your own judgement
   on each (the council can be wrong; you are the editor, not a relay).

For security-sensitive changes, prefer the `security_review` tool — same flow,
security-focused prompts plus a residual-risk section.
