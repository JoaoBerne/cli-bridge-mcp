---
name: CLI flag broken / drifted
about: A delegate CLI changed its flags and a lane no longer works
title: "[drift] "
labels: drift
---

**Which lane / CLI?**
e.g. `gemini` (agy), `gpt` (codex), `opencode` …

**What broke**
The error or wrong behavior you see (paste the `[kind] message`, e.g. `[failed] … exit 2`).

**The CLI's current invocation**
What the CLI now expects (paste the relevant `--help` excerpt):

```
<paste mycli --help here>
```

**Version**
- CLI version:
- cli-bridge version / commit:

> The nightly `drift-check` workflow opens these automatically when the test suite breaks; feel
> free to file one manually if you hit it first.
