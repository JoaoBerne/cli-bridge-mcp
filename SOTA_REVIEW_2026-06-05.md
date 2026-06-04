# External SOTA Review — 2026-06-05

**Audience:** the agent maintaining this repo.
**Epistemic status: these are LEADS, not verdicts.** This document was produced by an
external multi-agent web-research pass (4 parallel research agents + repo inventory) on
2026-06-05. Sources are cited, but several load-bearing claims come from secondary sources
or single studies. Each item carries a confidence tag:

- `[HIGH]` — primary source read directly (GitHub issue, official doc, paper).
- `[MED]` — consistent across 2+ secondary sources, primary not fully verified.
- `[LOW]` — single source, paraphrased, or potentially stale. Verify before acting.

Treat every item as a hypothesis to evaluate against this repo's own constraints
(stdlib-only, ban-safe, read-only default, thin server.py). Reject freely — but reject
explicitly, with a reason, in this file or the action plan. Section 7 lists the claims
that MUST be verified before any of this drives a decision.

---

## 1. Deliberation science: findings that challenge current defaults

The 2025–2026 literature moved against two mechanisms this repo ships. This is the most
consequential section.

### 1.1 Synthesis is the worst aggregation; judge-SELECTION is the best `[MED]`

- arXiv 2603.20324 ("When Agents Disagree: The Selection Bottleneck in Multi-Agent LLM
  Pipelines", Mar 2026, 42 tasks / 210 runs): diverse team + **judge-based selection** of
  the single best answer → win rate 0.810; diverse team + **MoA-style synthesis** → 0.179
  (loses to baseline 82% of the time); majority vote ≈ chance (0.496). Effect size g=3.86.
- arXiv 2502.00674 ("Rethinking Mixture-of-Agents"): Self-MoA (N samples from the single
  best model) beats mixed-model MoA — diversity only pays when aggregation preserves it.
- **Implication for this repo:** `ask_all synthesize=true` and the `consensus` chairman
  synthesis step are on the losing side of this result. The Borda ranking step in
  `consensus` is selection-shaped (good); the chairman rewrite afterward is
  synthesis-shaped (suspect). Hypothesis to test: default to "judge picks the best single
  answer, returns it verbatim + disagreement notes", synthesis opt-in.
- **Counterpoint to weigh:** these are benchmark tasks with a single correct answer.
  For open-ended advisory questions (this tool's main use), synthesis may still be what
  users want. Don't flip the default blindly — eval it (see §3).

### 1.2 Multi-agent debate loses to self-consist