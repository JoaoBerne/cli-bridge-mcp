<!-- Thanks for contributing! Keep diffs surgical and tests green. -->

## What & why
<!-- What does this change, and why? Link any issue. -->

## Checklist
- [ ] `pytest -q` is green (tests don't need a real CLI or network)
- [ ] `ruff check src/ tests/` is clean
- [ ] No new runtime dependency (stdlib + `mcp` only)
- [ ] `server.py` stays thin (logic lives in lanes/runner/router/workflows/findings/telemetry)
- [ ] Telemetry stays best-effort (never raises into a delegation)
- [ ] Cost safety preserved (empty model never resolves to paid)
- [ ] `CHANGELOG.md` updated under "Unreleased" (if user-facing)
- [ ] New env var / tool documented (README / ARCHITECTURE)

## Notes
<!-- Anything reviewers should know: new env vars, behavior changes, follow-ups. -->
