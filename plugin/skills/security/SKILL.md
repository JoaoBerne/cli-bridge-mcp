---
name: security
description: Cross-model security review of the current git diff — independent AI CLIs hunt vulnerabilities; decorrelated models catch what a single reviewer misses.
---

# Security — cross-model security review

1. Call the `security_review` MCP tool (server `cli-bridge`) with `cwd` set to the
   repository root (`base` for a non-default base ref).
2. The value of the council here is decorrelation: models from different vendors
   make different mistakes, so a vulnerability flagged by several independent CLIs
   is rarely a false positive. Lead with consensus findings.
3. Relay the residual-risk section honestly — it lists what the review could NOT
   rule out, which matters as much as the findings.
4. Verify each finding against the actual code before presenting it as real.
