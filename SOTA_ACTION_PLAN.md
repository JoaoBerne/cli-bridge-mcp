# cli-bridge SOTA Action Plan

Date: 2026-06-01

## Status (updated 2026-06-01)

**Shipped (P0–P2 complete + extras):**
- ✅ P0: config.py single-source; opencode free-model TTL cache; overflow prune.
- ✅ P1: terse delegate preamble (`CLI_BRIDGE_TERSE`, default lite); isolation guarantee + test.
- ✅ P2-7 `review_diff` · P2-8 trace+latency on cascade/ask_all · P2-9 opt-in response cache ·
  P2-10 MCP prompts · P2-11 `security_review` + `debate`.
- ✅ Extra (user-requested): opt-in **write/build mode** on every lane (bin-aware builders);
  **sibling-model self-consultation** (`ask_<host>` with explicit model).
- ✅ Telemetry + lane cooldown; deterministic cascade router; per-lane cost tiers.
- Suite: 119 tests green. Manifests: `smithery.yaml`, `server.json`.

**Still open / deferred:** async durable job system, web dashboard, OTel export, semantic
cache, worktree-isolated writers, retries w/ backoff, PyPI publish (user action).

---

Goal: turn `cli-bridge` from a useful MCP bridge into a high-trust, cost-aware, workflow-ready
multi-agent council that people can install in minutes and keep using daily.

This plan is based on a fresh scan of MCP/multi-agent/gateway/security repos and docs. It is
intentionally scoped for this repo's current architecture: small Python package, stdio MCP server,
official CLI subprocesses, no token extraction, minimal dependencies.

## Current Position

What cli-bridge already does well:

- Official CLI spawning: ban-safe and subscription-friendly.
- Host self-hide: Codex does not ask Codex, Claude does not ask Claude.
- Per-lane env config: bin/model/cost/enabled.
- Free/limited/paid stance: better than assuming "free means unlimited".
- Fan-out with bounded timeouts.
- Output spill files for large responses.
- Process-tree kill on timeout/cancel.
- Custom JSON lanes and BYO API via `curl`.

Where it is still behind SOTA:

- No async/durable job system, so long `ask_all` calls can still hit MCP host deadlines.
- No persistent lane health/cooldown counters.
- No router that chooses a lane based on task, failure history, quota, cost, and latency.
- No ready-made workflows (`review_diff`, `security_review`, `debate`, `premortem`).
- No machine-readable output contract beyond text.
- No local telemetry/reporting.
- No MCP prompts/resources for discoverable workflow templates.
- No prompt-injection/tool-output guard.
- No installer/setup CLI that edits or prints exact host config.
- No GitHub Action / PR workflow story.

## Value Thesis

The repo should not try to win by being "one more MCP that calls models". That market is already
crowded. The valuable product is:

> A local control plane for the AI CLI subscriptions a developer already pays for.

That means cli-bridge should own the boring but valuable layer:

- Which agent should be used for this task?
- Which lanes are healthy right now?
- Which lanes are free, limited, or paid for this user?
- Which run timed out, hit quota, or produced weak output?
- Which model agreed with which finding?
- How do I run the same review workflow tomorrow and get comparable output?
- How do I avoid giving write access or leaking secrets?

This is the gap between a toy bridge and useful infrastructure.

### What Would Make Users Star It

1. "It installed in 2 minutes and detected my CLIs."
2. "I can ask all agents without thinking about cost/quota."
3. "It does useful PR reviews, not generic advice."
4. "It does not hang my host session."
5. "It tells me which agent failed and why."
6. "It keeps my paid/limited quotas under control."
7. "It is safer than random MCP bridges."
8. "It works from Codex, Claude Code, opencode, and CI."

### Product Moat

The defensible angle is not model access. Models and CLIs change constantly. The moat is the local
policy/control layer:

- Ban-safe: official CLI subprocesses only.
- Local-first: no hosted gateway required.
- Cost-aware: user-specific free/limited/paid behavior.
- Evidence-aware: consensus findings with model attribution.
- Failure-aware: cooldowns, fallbacks, health reports.
- Workflow-aware: ready-made review/security/debate/test workflows.
- Security-aware: prompt-injection warnings and no write access by default.

### Killer Demo Path

The first public demo should show this exact flow:

```bash
uvx cli-bridge-mcp doctor
cli-bridge setup codex --write
cli-bridge review-diff --base origin/main --json
cli-bridge usage-report --since today
```

Then inside Codex or Claude:

```text
Use cli-bridge to review my diff with consensus.
```

Expected visible value:

- doctor detects installed CLIs.
- setup writes the host config or prints exact config.
- review runs multiple agents in parallel.
- output dedupes findings and labels consensus.
- usage report shows duration, status, and lanes used.

### Highest-Value Ideas To Add

| Idea | User value | MVP shape | Proof it works |
|---|---|---|---|
| Async jobs | No host timeout for slow agents | `ask_all_async`, `job_status`, `job_result` | returns job id in <1s |
| Lane health | Stops retrying broken agents | SQLite counters + cooldown | timeout lane skipped by `ask_all` |
| Smart router | User asks "best" instead of lane names | deterministic score + `route_plan` | explains selected/skipped lanes |
| Review workflow | Daily developer use | `review_diff` JSON + Markdown | finds seeded bug in fixture |
| Security workflow | Trust signal | `security_review` with OWASP prompts | flags injected shell fixture |
| Setup CLI | Removes install friction | `cli-bridge setup codex --write` | backup + valid config |
| Usage report | Cost/quota trust | `usage_report` by lane/model/status | shows last runs |
| Prompt guard | Safer MCP output | `CLI_BRIDGE_GUARD=warn|strict` | catches obvious injection |
| Worktree isolation | Safe write-capable agents | run edits in temp worktree | original tree unchanged |
| MCP prompts | Native workflow discovery | `prompts/list`, `prompts/get` | client sees templates |
| GitHub Action | Viral repo use | self-hosted runner example | posts PR comment |
| Evals | Proves quality | fixtures + golden JSON checks | CI catches regressions |

### Ideas To Avoid Until Later

- Hosted SaaS dashboard.
- Browser session scraping.
- Big LangGraph/Temporal dependency in core.
- Auto-writing code in the user's real worktree.
- API-first rewrite.
- Many niche lanes before the core UX is reliable.
- Complex debate loops before `review_diff` is good.

## SOTA Findings

### 1. Durable workflow engines beat blocking MCP calls

Repos/docs:

- [lastmile-ai/mcp-agent](https://github.com/lastmile-ai/mcp-agent)
- [mcp-agent durable agents docs](https://docs.mcp-agent.com/mcp-agent-sdk/advanced/durable-agents)
- [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph)
- [GitHub Security Lab taskflow-agent](https://github.com/GitHubSecurityLab/seclab-taskflow-agent)

Takeaway:

The strongest agent architectures separate "start work" from "wait for completion". mcp-agent and
LangGraph emphasize durability, pause/resume, retries, and human oversight. Taskflow shows that
YAML-declared workflows plus checkpoints make agent runs reproducible and resumable.

What cli-bridge should do:

- Add async tools first without adding Temporal/LangGraph dependency.
- Store job metadata/results in SQLite.
- Mark interrupted jobs on server startup.
- Later offer optional Temporal adapter only if demand exists.

### 2. Best bridges provide both MCP and human CLI surfaces

Repos:

- [mkXultra/ai-cli-mcp](https://github.com/mkXultra/ai-cli-mcp)
- [BeehiveInnovations/pal-mcp-server](https://github.com/BeehiveInnovations/pal-mcp-server)
- [religa/multi_mcp](https://github.com/religa/multi_mcp)
- [wraptc](https://briansunter.com/projects/wraptc)

Takeaway:

The better bridge repos do not only expose MCP tools. They also expose a human-facing CLI for
testing, setup, live E2E, JSON output, and debugging outside the host assistant.

What cli-bridge should do:

- Keep `cli-bridge-mcp` as MCP server.
- Add `cli-bridge` CLI for `doctor`, `setup`, `models`, `ask`, `ask-all`, `jobs`, `stats`.
- Make the MCP tools call the same internal service code as the CLI.

### 3. Routing/fallback/cooldown is a core feature, not polish

Repos/docs:

- [wraptc](https://briansunter.com/projects/wraptc)
- [Routerly](https://github.com/Inebrio/Routerly)
- [Portkey fallback docs](https://portkey.ai/docs/product/ai-gateway/fallbacks)
- [LiteLLM monitoring/rate-limit ecosystem](https://www.sumologic.com/help/docs/integrations/saas-cloud/litellm/)

Takeaway:

Production LLM gateways track provider health, rate limits, budgets, latency, and retryability.
They avoid providers in cooldown and fall back automatically when safe.

What cli-bridge should do:

- Track per-lane success/failure/timeout/quota/auth.
- Add cooldown after repeated `timeout`, `auth`, or `quota`.
- Add `ask_best` router.
- Let `ask_all` skip unhealthy lanes unless `force=true`.

### 4. Workflow templates create sticky usage

Repos/docs:

- [multi_mcp](https://github.com/religa/multi_mcp)
- [AI Code Reviewer](https://github.com/calimero-network/ai-code-reviewer)
- [MCP prompts docs, Apollo](https://www.apollographql.com/docs/apollo-mcp-server/prompts)
- [FastMCP prompts](https://gofastmcp.com/v2/clients/prompts)

Takeaway:

Users do not want to remember which prompt to use. Successful repos expose named workflows:
review, security audit, debate, consensus, premortem, test plan, docs generation.

What cli-bridge should do:

- Expose workflow tools as MCP tools and as MCP prompts.
- Make workflows produce structured results with findings, severity, confidence, model agreement.
- Start with code review and security review, because they demo well and are useful daily.

### 5. Security is now a headline feature for MCP

Repos/docs:

- [mcpfw](https://mcpfw.dev/)
- [mcp-scan](https://github.com/invariantlabs-ai/mcp-scan)
- [secure-hulk](https://github.com/AppiumTestDistribution/secure-hulk)
- [OWASP MCP Tool Poisoning](https://owasp.org/www-community/attacks/MCP_Tool_Poisoning)
- [Trail of Bits MCP security wrapper](https://www.trailofbits.com/mcp/)

Takeaway:

MCP risk is not theoretical: prompt injection, tool poisoning, data exfiltration, billing
amplification, and rug-pull behavior are now expected concerns. cli-bridge is safer than many
bridges because it is read-only by default, but it still forwards untrusted tool/model output to the
host context.

What cli-bridge should do:

- Add a response guard before returning delegate output.
- Detect common injection/exfiltration patterns.
- Redact secrets already, but add "suspicious output" warnings.
- Add canary mode for sensitive runs.
- Never let a delegated agent edit local files except explicit `opencode agent=build`, and document
that it should be isolated later.

### 6. Observability differentiates serious infra from toys

Repos/docs:

- [Langfuse](https://github.com/langfuse/langfuse)
- [Langfuse observability docs](https://langfuse.com/docs/observability/overview/)
- [Helicone sessions](https://docs.helicone.ai/features/sessions)
- [OpenAI Agents SDK tracing](https://openai.github.io/openai-agents-python/ref/tracing/)

Takeaway:

LLM systems need traces, sessions, latency, model, token/cost estimates, tool spans, and result
quality feedback. cli-bridge cannot always get true token usage from CLIs, but it can still track
duration, chars, exit kind, selected model, and approximate cost/quota.

What cli-bridge should do:

- Add local SQLite telemetry.
- Add `usage_report`, `lane_stats`, `export_traces`.
- Use OpenTelemetry-like JSON shape so later Langfuse/OTel export is easy.

### 7. Specialist review agents beat generic "ask all"

Repos/docs:

- [AI Code Reviewer](https://github.com/calimero-network/ai-code-reviewer)
- [multi_mcp](https://github.com/religa/multi_mcp)
- [Diffwise](https://diffwise.app/)
- [Anthropic Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)

Takeaway:

Multi-agent value comes from role diversity, not only model diversity. Security, performance,
correctness, maintainability, and test coverage reviewers should get different prompts and a
merge/judge step.

What cli-bridge should do:

- `review_diff` should run role prompts across lanes.
- Merge duplicate findings.
- Score confidence by agreement count and severity.
- Output GitHub-compatible Markdown and JSON.

### 8. MCP native surfaces beyond tools matter

Docs:

- [MCP prompts, Apollo](https://www.apollographql.com/docs/apollo-mcp-server/prompts)
- [FastMCP elicitation](https://fastmcp.mintlify.app/servers/elicitation)
- [Cloudflare human-in-the-loop / MCP elicitation](https://github.com/cloudflare/agents/blob/main/docs/human-in-the-loop.md)

Takeaway:

Tools are only one MCP primitive. Prompts make workflows discoverable. Elicitation lets a server
request structured user input for setup or risky operations when the client supports it.

What cli-bridge should do:

- Add `list_prompts` / `get_prompt` support if low-level MCP server supports it cleanly.
- Ship prompts: `review_diff`, `security_review`, `architecture_debate`, `cost_setup`.
- Keep `setup` tool fallback for clients without elicitation.

### 9. The 2026 agent stack is a control plane

Repos/docs:

- [AI Agent Architecture Explained: 4 Layers + Patterns](https://decodethefuture.org/en/ai-agent-architecture-explained/)
- [The 2026 AI Agent Stack](https://aiagentrank.io/blog/ai-agent-stack-2026)
- [Thoughtworks Technology Radar 2026](https://www.thoughtworks.com/content/dam/thoughtworks/documents/radar/2026/04/tr_technology_radar_vol_34_en.pdf)

Takeaway:

The recurring architecture is model + orchestration + tools/MCP + memory + observability + evals +
guardrails. The winning systems are not just "LLM calls"; they provide control, replay, visibility,
and boundaries.

What cli-bridge should do:

- Be explicit that it is the local control plane for AI CLIs.
- Add the missing control-plane pieces in order: telemetry, health, async jobs, router, workflows.
- Keep dependencies light until the architecture proves it needs heavier orchestration.

### 10. Gateway value comes from budgets, fallback, caching, and attribution

Repos/docs:

- [LLM Gateway 2026 guide](https://klymentiev.com/blog/llm-gateway-guide)
- [AI Gateway practitioner's guide](https://www.respan.ai/ai-gateway)
- [MCP Best Practices](https://mcp-best-practice.github.io/mcp-best-practice/best-practice/)

Takeaway:

Gateways win because they make provider choice operational: budgets, routing, failover,
observability, policy, and attribution. cli-bridge is not an OpenAI-compatible gateway, but it can
borrow the same control-plane concepts for local CLIs.

What cli-bridge should do:

- Add per-lane daily limits and reset time.
- Add per-profile behavior: saver/balanced/max.
- Add fallback from `ask_best` when a lane returns timeout/quota/auth.
- Add run attribution: tool, workflow, lane, model, status, duration.

### 11. Local-first repo review should be evidence-first

Repos/docs:

- [RepoReviewer paper](https://arxiv.org/abs/2603.16107)
- [AI Code Reviewer](https://github.com/calimero-network/ai-code-reviewer)
- [Code Broker paper](https://arxiv.org/abs/2604.23088)
- [Agora multi-agent bug detection](https://arxiv.org/abs/2605.29910)

Takeaway:

Code review agents are valuable when they are local-first, role-specialized, and evidence-backed.
The strongest pattern is hierarchical: orchestrator -> specialized reviewers -> synthesizer. Deep
bug detection benefits from domain-aware agents, not just generic majority vote.

What cli-bridge should do:

- Build `review_diff` as an orchestrated workflow, not raw `ask_all`.
- Give each reviewer a role and narrow checklist.
- Require evidence: file, line, snippet, reasoning.
- Judge should merge and rank findings, not invent new ones.
- Add deterministic prechecks before LLM calls: large diff detection, docs-change detection,
  dangerous shell patterns, secret regexes, missing tests.

### 12. Security value needs runtime policy, not only warnings

Repos/docs:

- [MCP Trail security best practices](https://mcptrail.com/blog/mcp-security-best-practices/)
- [MCP Best Practices](https://mcp-best-practice.github.io/mcp-best-practice/best-practice/)
- [Authenticated Workflows paper](https://arxiv.org/abs/2602.10465)
- [MCP Tool Poisoning, OWASP](https://owasp.org/www-community/attacks/MCP_Tool_Poisoning)

Takeaway:

Modern agent security is moving from "prompt guardrails" to policy enforcement, audit trails,
scoped permissions, rate limits, and human approval. cli-bridge can implement a lightweight local
version without becoming a full firewall.

What cli-bridge should do:

- Add a policy layer before execution:
  - lane allowed?
  - write-capable?
  - limited/paid allowed?
  - cwd allowed?
  - max parallel allowed?
  - timeout within cap?
- Add audit rows for every tool call.
- Add `approval_required` for write-capable tools and future apply-patch tools.
- Add `policy_report` so users can see what is allowed.

### 13. Evals should ship before big workflow expansion

Repos/docs:

- [Langfuse eval/dataset model](https://github.com/langfuse/langfuse)
- [Helicone sessions](https://docs.helicone.ai/features/sessions)
- [AI Code Reviewer](https://github.com/calimero-network/ai-code-reviewer)

Takeaway:

Once prompts become product logic, regressions are easy. Successful LLM products use traces and
datasets to compare changes. cli-bridge should ship small local evals before adding many workflow
prompts.

What cli-bridge should do:

- Add `tests/fixtures/reviews/` with known buggy diffs.
- Add a no-network evaluator for parser/deduper/schema logic.
- Add opt-in live evals for real models.
- Store workflow prompt versions in telemetry.
- Add `cli-bridge eval review-diff --fixture ...` later.

## Architecture Target

Keep core simple:

```text
src/cli_bridge/
  __main__.py          # server entry only
  cli.py               # human CLI entrypoint
  config.py            # env + config file parsing
  detect.py            # installed CLIs
  lanes.py             # lane registry + argv builders
  runner.py            # subprocess execution, redaction, kill group
  server.py            # MCP surface only, thin dispatch
  jobs.py              # async jobs + result files + SQLite persistence
  telemetry.py         # run records, lane health, reports
  router.py            # lane selection, cooldown, fallback
  workflows.py         # review/security/debate/premortem orchestration
  guards.py            # prompt injection/output guard
  prompts.py           # MCP prompt templates
```

Principle:

- `server.py` should not own business logic.
- MCP tools and human CLI should call the same functions.
- SQLite should be optional but default-on in user config dir.
- No heavy orchestration dependency until the lightweight architecture proves insufficient.

## Data Model

Use stdlib `sqlite3`. Default path:

```text
~/.local/share/cli-bridge/state.sqlite
```

Override:

```text
CLI_BRIDGE_STATE_DB=/path/to/state.sqlite
```

Tables:

```sql
CREATE TABLE runs (
  id TEXT PRIMARY KEY,
  job_id TEXT,
  tool TEXT NOT NULL,
  lane TEXT,
  model TEXT,
  cwd TEXT,
  task_hash TEXT NOT NULL,
  task_preview TEXT NOT NULL,
  status TEXT NOT NULL,
  kind TEXT NOT NULL,
  exit_code INTEGER,
  timeout_s INTEGER NOT NULL,
  input_chars INTEGER NOT NULL,
  output_chars INTEGER NOT NULL,
  estimated_input_tokens INTEGER NOT NULL,
  estimated_output_tokens INTEGER NOT NULL,
  reported_input_tokens INTEGER,
  reported_output_tokens INTEGER,
  estimated_credits REAL,
  reported_credits REAL,
  usage_source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  duration_ms INTEGER,
  result_path TEXT
);

CREATE TABLE lane_state (
  lane TEXT PRIMARY KEY,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  consecutive_timeouts INTEGER NOT NULL DEFAULT 0,
  cooldown_until TEXT,
  last_kind TEXT,
  last_model TEXT,
  last_run_at TEXT,
  daily_count INTEGER NOT NULL DEFAULT 0,
  daily_reset_at TEXT
);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  cwd TEXT,
  task_hash TEXT NOT NULL,
  task_preview TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  result_path TEXT,
  error TEXT
);
```

Privacy:

- Store task hash + preview only by default.
- Do not store full prompt/output unless `CLI_BRIDGE_STORE_TRANSCRIPTS=true`.
- Result files already exist for large outputs; reuse overflow dir pattern.
- Token and credit tracking must be useful but honest: local estimates are not provider invoices.

## Action Plan

### Phase 0 - Repo Hygiene Before More Features

Why:

The repo is still compact. Add structure before adding more logic to `server.py`.

Tasks:

1. Create `config.py`.
2. Move profile/cost helpers from `server.py` into `config.py`.
3. Keep `LaneSpec` env lookup in `lanes.py` for now.
4. Add unit tests for config parsing.
5. Add `ruff`/format only if project owner wants style tooling. Do not add churn otherwise.

Files:

- `src/cli_bridge/config.py`
- `src/cli_bridge/server.py`
- `tests/test_config.py`

Acceptance:

- `pytest -q` passes.
- `server.py` loses profile/setup parsing details.
- No behavior change.

### Phase 1 - Local Telemetry + Lane Health

Why:

Routing and cooldown need facts. Guessing from current process state is not enough.
The user also needs a local answer to: "How many tokens, credits, and scarce requests did my main
CLI session burn through cli-bridge?"

Important truth:

Most official CLIs do not expose reliable token/credit usage in a stable machine-readable format.
Some print nothing, some print progress banners, some may change output formats. The SOTA design
must therefore separate:

- **Observed usage**: exact facts cli-bridge can measure itself.
- **Reported usage**: true provider numbers, only when a lane exposes them reliably.
- **Estimated usage**: local approximation from prompt/output chars.
- **Configured credit cost**: user-provided price/credit mapping when the provider does not expose
  real billing.

Never pretend estimates are exact. Label them clearly.

Tasks:

1. Add `telemetry.py`.
2. Add `RunRecord` dataclass.
3. Wrap every `runner.arun` call with telemetry write:
   - lane
   - model
   - status/kind
   - duration
   - timeout
   - output chars
4. Add token/credit accounting:
   - `input_chars`: exact prompt length
   - `output_chars`: exact returned text length
   - `estimated_input_tokens`: `ceil(input_chars / 4)`
   - `estimated_output_tokens`: `ceil(output_chars / 4)`
   - `reported_input_tokens`: nullable
   - `reported_output_tokens`: nullable
   - `reported_credits`: nullable
   - `estimated_credits`: nullable, derived from config
   - `usage_source`: `observed|reported|estimated|configured`
5. Add lane health update:
   - timeout increments `consecutive_timeouts`
   - auth/quota/timeout increments `consecutive_failures`
   - ok resets counters
6. Add cooldown policy:
   - 2 timeouts: cooldown 15 minutes
   - auth: cooldown until user resets or doctor deep passes
   - quota: cooldown 1 hour by default
7. Add MCP tools:
   - `lane_stats`
   - `usage_report`
   - `reset_lane_state`
8. Add CLI:
   - `cli-bridge stats`
   - `cli-bridge usage`
   - `cli-bridge reset-lane gemini`

CLI shape:

```bash
cli-bridge usage
cli-bridge usage --since today
cli-bridge usage --since 7d --by lane
cli-bridge usage --by model --json
cli-bridge usage --session current
```

Example human output:

```text
cli-bridge usage --since today

Lane       Runs  OK  Timeout  In tok est  Out tok est  Credits est  Credits reported
gemini       4   3        1       12,400        5,210            -                 -
mistral      2   2        0        3,050        1,440            -                 -
opencode     1   0        1          420            0         0.00                 -

Notes:
- token counts are estimates unless marked "reported"
- credit counts require provider reporting or CLI_BRIDGE_<LANE>_CREDITS_PER_1K_* config
```

MCP tool shape:

```json
{
  "since": "today|24h|7d|all|ISO-8601",
  "group_by": "lane|model|tool|day",
  "format": "text|json"
}
```

SOTA accounting policy:

- Always store raw exact counts that are local and safe: chars, duration, status, model.
- Estimate tokens locally with a documented heuristic, default `chars / 4`.
- Allow per-lane override:
  - `CLI_BRIDGE_<LANE>_TOKEN_ESTIMATE_CHARS=4`
  - `CLI_BRIDGE_<LANE>_CREDITS_PER_1K_INPUT`
  - `CLI_BRIDGE_<LANE>_CREDITS_PER_1K_OUTPUT`
  - `CLI_BRIDGE_<LANE>_CREDITS_PER_REQUEST`
- If a lane later supports true usage parsing, store it separately as `reported_*`.
- Never parse usage from arbitrary natural-language text unless parser is lane-specific and tested.
- Do not store full prompts/output by default; usage tracking must be privacy-safe.

Files:

- `src/cli_bridge/telemetry.py`
- `src/cli_bridge/server.py`
- `src/cli_bridge/cli.py`
- `pyproject.toml`
- `tests/test_telemetry.py`

Acceptance:

- Running `ask_mistral` creates one `runs` row.
- `cli-bridge usage --json` returns valid JSON without contacting any model.
- Usage report labels tokens as `estimated` unless true provider values exist.
- Credit estimate stays empty unless credit config is set.
- With `CLI_BRIDGE_OPENCODE_CREDITS_PER_REQUEST=1`, one opencode run reports `estimated_credits=1`.
- Current-session aggregation works for all MCP calls made by one server process.
- Timeout test creates cooldown.
- `doctor` shows `cooldown` next to a cooled lane.
- `ask_all` skips cooled lanes unless `force=true`.
- Full tests pass.

### Phase 2 - Async Jobs

Why:

MCP hosts have tool-call deadlines. Long council runs need "start now, poll later".

Tools to add:

- `ask_all_async`
- `job_status`
- `job_result`
- `job_cancel`
- `jobs_list`

Behavior:

```text
ask_all_async(task="review this", synthesize=true)
-> job_id: "job_..."
-> status: running

job_status(job_id)
-> running | succeeded | failed | cancelled | interrupted

job_result(job_id)
-> same body as ask_all, or path if large
```

Implementation:

1. Add `jobs.py`.
2. Use in-process `asyncio.create_task` for v1.
3. Store job rows in SQLite.
4. Store final result in overflow dir.
5. On server startup, mark jobs still `running` as `interrupted`.
6. Do not promise cross-restart continuation in v1.

Files:

- `src/cli_bridge/jobs.py`
- `src/cli_bridge/server.py`
- `tests/test_jobs.py`

Acceptance:

- `ask_all_async` returns in under 1 second.
- Job result is retrievable after completion.
- Cancel kills process groups.
- Restart marks running jobs interrupted.

### Phase 3 - Smart Router

Why:

Users should be able to say "ask best model" without manually knowing current quota/health.

Tools:

- `ask_best`
- `route_plan`

Routing inputs:

- task length
- requested mode: `fast | cheap | deep | code | review | security`
- lane `cost_label`: free/limited/paid
- health/cooldown
- installed status
- model default availability
- historical timeout rate

Initial policy:

```text
fast: mistral -> gemini -> opencode
cheap: free non-limited healthy lanes only
deep: claude/gemini/opencode if allowed by profile
code: gpt host hidden, so gemini/opencode/claude depending host
security: at least two lanes, prefer diverse providers
```

Do not overfit. Use deterministic scoring first:

```text
score = priority
      - cost_penalty
      - limited_penalty
      - latency_penalty
      - cooldown_block
      - failure_penalty
      + capability_bonus
```

Files:

- `src/cli_bridge/router.py`
- `tests/test_router.py`

Acceptance:

- Router never selects a cooled lane unless `force=true`.
- Router respects `CLI_BRIDGE_PROFILE=saver|balanced|max`.
- Router explains why it chose/skipped lanes.
- `route_plan` is pure read-only and JSON-friendly.

### Phase 4 - Workflow Tools

Why:

Workflows are what users star and reuse. Generic `ask_all` is infrastructure; `review_diff` is value.

#### Tool: `review_diff`

Inputs:

- `base_ref` default `HEAD`
- `cwd`
- `scope`: `diff | staged | working_tree | path`
- `depth`: `quick | normal | deep`
- `output_format`: `markdown | json`

Pipeline:

1. Gather diff with `git diff`.
2. If diff too large, summarize file list + chunk by file.
3. Spawn role reviewers:
   - correctness
   - security
   - tests
   - maintainability
4. Merge findings by file/line/title similarity.
5. Score:
   - severity: low/medium/high/blocker
   - confidence: single/majority/consensus
   - models: list
6. Return grouped review.

Files:

- `src/cli_bridge/workflows.py`
- `tests/test_workflows_review.py`

Acceptance:

- Works with no git changes: returns "no diff".
- JSON output validates against schema.
- Markdown output is GitHub PR-comment friendly.
- No writes to repo.

#### Tool: `security_review`

Pipeline:

1. Use diff or path.
2. Role prompts:
   - auth/session
   - injection/secrets
   - file/network/shell
   - dependency/supply-chain
3. Include OWASP checklist references in prompt.
4. Return only actionable findings.

Acceptance:

- Does not invent line numbers if unavailable.
- Flags clear dangerous shell construction in fixture.
- Has `residual_risk` section.

#### Tool: `debate`

Pipeline:

1. Ask 2-4 lanes for independent answer.
2. Ask each lane to critique one opposing answer if budget/profile allows.
3. Judge summarizes agreement/disagreement and recommends.

Acceptance:

- Has max rounds.
- Never runs unbounded loops.
- Shows which model said what.

### Phase 5 - MCP Prompts and Resources

Why:

MCP clients can discover server-provided workflows. This makes cli-bridge feel native, not only a
bag of tools.

Prompts to expose:

- `review_diff`
- `security_review`
- `architecture_debate`
- `cost_setup`
- `test_plan`
- `incident_premortem`

Resources to expose:

- `cli-bridge://config`
- `cli-bridge://lane-stats`
- `cli-bridge://usage-summary`
- `cli-bridge://workflow-schemas/review-diff`

Implementation:

1. Check low-level `mcp` Python SDK support for `list_prompts` / `get_prompt`.
2. If supported, add `prompts.py`.
3. Keep prompt text versioned as Python strings or small `.md` files in package data.
4. Add tests over prompt names and required args.

Acceptance:

- Client can list prompts.
- Prompt templates include arguments and clear tool sequence.
- No duplication between workflow tool prompts and MCP prompts beyond shared constants.

### Phase 6 - Security Guard

Why:

cli-bridge returns untrusted model/CLI output to the host assistant. Output can contain instructions
that try to manipulate the host, leak secrets, or burn credits.

Features:

- `CLI_BRIDGE_GUARD=off|warn|strict`, default `warn`.
- Pattern scanner for:
  - "ignore previous instructions"
  - credential exfiltration requests
  - hidden markdown/HTML comments
  - shell commands disguised as model instructions
  - "call tool X with secret Y"
- Canary mode:
  - insert random canary instruction into delegate prompt for sensitive workflows
  - if output repeats or follows canary, mark as suspicious

Files:

- `src/cli_bridge/guards.py`
- `tests/test_guards.py`

Acceptance:

- Suspicious output is wrapped with warning in `warn`.
- Suspicious output is blocked in `strict`.
- Benign code review output is not blocked.
- Redaction still runs before guard output.

### Phase 7 - Worktree Isolation for Write-Capable Agents

Why:

`opencode agent=build` can edit files. SOTA coding agents isolate edits and return diffs.

Tool:

- `ask_opencode_build_isolated`

Behavior:

1. Create temporary git worktree.
2. Run write-capable agent inside worktree.
3. Return `git diff`.
4. Do not apply changes to original repo.
5. Add `apply_patch_from_job` only later, with explicit user approval.

Files:

- `src/cli_bridge/worktrees.py`
- `tests/test_worktrees.py`

Acceptance:

- Original repo unchanged.
- Diff path returned.
- Worktree cleaned unless `CLI_BRIDGE_KEEP_WORKTREES=true`.

### Phase 8 - Setup CLI

Why:

README setup is not enough. "It just works" drives adoption.

Commands:

```bash
cli-bridge setup codex
cli-bridge setup claude
cli-bridge setup opencode
cli-bridge doctor --deep --json
cli-bridge models opencode
cli-bridge ask gemini "hello"
cli-bridge ask-all "compare these options" --json
```

Implementation:

1. Add `cli.py` using stdlib `argparse`.
2. For setup commands:
   - print exact config by default
   - `--write` edits config after backup
3. Detect paths:
   - Python executable
   - uvx install path
   - host config file
4. Never overwrite without backup.

Acceptance:

- `cli-bridge doctor --json` works outside MCP.
- `cli-bridge setup codex` prints valid TOML.
- `cli-bridge setup codex --write` backs up config first.

### Phase 9 - GitHub Action / CI Story

Why:

GitHub visibility comes from a demo people can paste into their own repos.

Artifacts:

- `.github/workflows/cli-bridge-review.yml`
- `examples/github-action-review.yml`
- README section: "Review PR with your local/self-hosted runner"

Important constraint:

Hosted GitHub runners will not have the user's logged-in CLIs. This is a self-hosted runner story,
or an API/custom-lane story.

Action flow:

```yaml
on: pull_request
jobs:
  review:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - run: cli-bridge review-diff --base origin/main --json > review.json
      - run: cli-bridge github-comment review.json
```

Acceptance:

- Docs clearly say self-hosted runner required for subscription CLIs.
- JSON output works with `reviewdog` or simple PR comment script.

### Phase 10 - Release Readiness

Tasks:

1. Add `CHANGELOG.md`.
2. Add `CONTRIBUTING.md`.
3. Add `SECURITY.md`.
4. Add issue templates:
   - bug
   - lane request
   - CLI flag broken
   - security report
5. Add screenshots/GIF:
   - doctor
   - ask_all
   - review_diff
   - async job
6. Publish to PyPI.
7. Add badges:
   - PyPI
   - tests
   - license
   - Python versions

Acceptance:

- Fresh user can install with `uvx cli-bridge-mcp`.
- Fresh user can run `cli-bridge setup codex`.
- README quickstart works without local repo path.

## Implementation Order by PR

### PR 1 - Config Extraction

Scope:

- Add `config.py`.
- Move profile/setup helpers.
- No behavior change.

Risk: low.

Tests:

- Existing tests.
- New config tests.

### PR 2 - Telemetry SQLite

Scope:

- Add `telemetry.py`.
- Record runs.
- Add `usage_report`.

Risk: medium. File permissions and privacy need care.

Tests:

- Temp SQLite path.
- No transcript stored by default.
- Run rows written for ok/timeout/auth/quota.

### PR 3 - Lane Cooldown

Scope:

- Lane state.
- Cooldown in doctor.
- `ask_all` skip cooled lanes.

Risk: medium. Avoid surprising direct `ask_<lane>` calls.

Policy:

- Direct `ask_<lane>` should still run unless `respect_cooldown=true`.
- `ask_all` should skip cooled lanes by default.

### PR 4 - Async Jobs

Scope:

- `ask_all_async`, `job_status`, `job_result`, `job_cancel`.
- Result persistence.

Risk: medium-high. Cancellation/process cleanup must be tested.

### PR 5 - Human CLI

Scope:

- `cli-bridge doctor/stats/ask/ask-all`.
- Shared service layer.

Risk: medium. Packaging entry points.

### PR 6 - Router

Scope:

- `ask_best`, `route_plan`.
- Deterministic score.

Risk: medium. Must explain decisions.

### PR 7 - `review_diff`

Scope:

- Git diff collection.
- Role reviewers.
- Merge findings.
- JSON + Markdown.

Risk: high. Biggest user-facing value, biggest prompt quality risk.

### PR 8 - Security Guard

Scope:

- `guards.py`.
- `CLI_BRIDGE_GUARD`.
- Warnings/strict block.

Risk: medium. False positives.

### PR 9 - MCP Prompts

Scope:

- Reusable prompt templates.
- Prompt list/get handlers.

Risk: low-medium depending SDK surface.

### PR 10 - Worktree Isolation

Scope:

- Isolated write-capable opencode build.
- Return diff only.

Risk: high. Git edge cases.

## Backlog Details

### New MCP Tools

| Tool | Priority | Description |
|---|---:|---|
| `usage_report` | P0 | Local run stats by lane/model/status. |
| `usage_budget` | P0 | Show configured daily limits and current estimated/reported usage. |
| `lane_stats` | P0 | Health, cooldown, avg latency, failure counts. |
| `reset_lane_state` | P0 | Clear cooldown/quota state. |
| `ask_all_async` | P0 | Start fan-out job and return job id immediately. |
| `job_status` | P0 | Poll async job. |
| `job_result` | P0 | Fetch async job result. |
| `job_cancel` | P0 | Kill running delegates. |
| `ask_best` | P1 | Router-selected lane. |
| `route_plan` | P1 | Explain lane selection without executing. |
| `review_diff` | P1 | Multi-agent code review workflow. |
| `security_review` | P1 | Security-focused review workflow. |
| `debate` | P2 | Multi-round model debate. |
| `premortem` | P2 | Risk analysis before implementation. |
| `test_plan` | P2 | Test strategy from diff or files. |
| `ask_build_isolated` | P2 | Write-capable isolated worktree job. |

### Config Variables

Keep existing:

- `CLI_BRIDGE_<LANE>_COST=free|limited|paid`
- `CLI_BRIDGE_<LANE>_ENABLED=false`
- `CLI_BRIDGE_<LANE>_BIN`
- `CLI_BRIDGE_<LANE>_MODEL`
- `CLI_BRIDGE_PROFILE=saver|balanced|max`

Add:

- `CLI_BRIDGE_STATE_DB`
- `CLI_BRIDGE_STORE_TRANSCRIPTS=false`
- `CLI_BRIDGE_GUARD=warn`
- `CLI_BRIDGE_MAX_PARALLEL=4`
- `CLI_BRIDGE_<LANE>_DAILY_LIMIT`
- `CLI_BRIDGE_<LANE>_RESET_HOUR_UTC`
- `CLI_BRIDGE_<LANE>_PRIORITY`
- `CLI_BRIDGE_<LANE>_TIMEOUT`
- `CLI_BRIDGE_<LANE>_TOKEN_ESTIMATE_CHARS=4`
- `CLI_BRIDGE_<LANE>_CREDITS_PER_REQUEST`
- `CLI_BRIDGE_<LANE>_CREDITS_PER_1K_INPUT`
- `CLI_BRIDGE_<LANE>_CREDITS_PER_1K_OUTPUT`
- `CLI_BRIDGE_SESSION_ID`
- `CLI_BRIDGE_LIVE_E2E=1`

### JSON Result Schema for Review Findings

```json
{
  "tool": "review_diff",
  "status": "ok",
  "summary": "string",
  "findings": [
    {
      "id": "F001",
      "severity": "low|medium|high|blocker",
      "confidence": "single|majority|consensus",
      "title": "string",
      "file": "path/or/null",
      "line": 123,
      "models": ["gemini", "mistral"],
      "evidence": "string",
      "recommendation": "string"
    }
  ],
  "residual_risk": "string",
  "lanes": [
    {"lane": "gemini", "status": "ok", "model": "x", "duration_ms": 1200}
  ]
}
```

### Prompt Design Rules

- Ask each reviewer for JSON first; convert to Markdown later.
- Tell reviewers to report only actionable issues.
- Tell reviewers to use `file=null,line=null` if exact line is unknown.
- Deduplicate before judging.
- Judge should not create new findings unless it can cite which agent raised it.

### Live E2E Strategy

Unit tests should not require real CLIs or network.

Add opt-in live tests:

```bash
CLI_BRIDGE_LIVE_E2E=1 pytest tests/test_live_e2e.py -q
```

Live test matrix:

- `doctor deep`
- one installed free lane says `OK`
- `ask_all` with timeout 15
- `opencode models` if opencode installed

Skip if:

- CLI missing
- env says lane disabled
- no auth

### Security Policy

Default posture:

- Read-only by default.
- No token extraction.
- No browser profile scraping.
- No automatic file edits except explicit write tools.
- No hidden paid lane use.
- No storing full transcripts by default.

`SECURITY.md` should include:

- How to report prompt injection/tool poisoning.
- Threat model.
- What cli-bridge does and does not protect against.
- Recommendation to run untrusted write-capable agents in isolated worktrees.

## Anti-Features

Do not add these unless explicitly chosen later:

- Browser session scraping for ChatGPT/Claude/Gemini.
- OAuth token extraction.
- Auto-running paid models by default.
- Long-lived daemon before async jobs prove need.
- Full LangGraph/Temporal dependency in core package.
- Agent write permissions in default `ask_all`.
- Hidden cloud telemetry.

## Marketing/README Positioning

Strong headline:

> Ban-safe multi-agent council for the AI CLIs you already pay for.

Subheadline:

> Claude, Codex, Gemini, Mistral, OpenCode and custom CLIs behind one MCP server: cost-aware,
> quota-aware, async, observable, and read-only by default.

Demo order:

1. `doctor` shows installed lanes.
2. `ask_all "review this diff"` returns parallel answers.
3. `review_diff` returns consensus findings.
4. `usage_report` shows what was spent/used.
5. `ask_all_async` avoids timeout.

## Success Metrics

Repository quality:

- `pytest -q` under 15s.
- Core dependency count stays small.
- New features have no live-provider dependency in unit tests.
- `server.py` remains thin.

User adoption:

- First install under 5 minutes.
- Works with local repo path and with `uvx`.
- README has copy-paste configs for Codex, Claude Code, opencode.
- At least one demo GIF or terminal cast.

Product usefulness:

- `ask_all` no longer times out for normal use.
- `review_diff` produces useful findings on this repo itself.
- `usage_report` helps user understand quota burn.
- Security guard catches obvious injection strings without blocking normal answers.

## Recommended Next Commit

Implement the smallest value-producing slice, not a huge framework:

1. `config.py` extraction.
2. `telemetry.py` SQLite run records.
3. `usage_report` tool.
4. `lane_stats` tool.
5. `doctor` shows health/cooldown from SQLite.

Do not start with workflows. Workflows need telemetry/cooldown first, otherwise bugs are harder to
debug and demos will be flaky.

## First 30-Day Build Plan

Week 1:

- Extract config.
- Add SQLite telemetry.
- Add `usage_report` and `lane_stats`.
- Add docs for state/privacy.

Week 2:

- Add cooldown policy.
- Add `ask_all_async`, `job_status`, `job_result`, `job_cancel`.
- Add `cli-bridge jobs`.

Week 3:

- Add `cli-bridge` human CLI surface.
- Add `setup codex`, `setup claude`, `doctor --json`.
- Add live E2E opt-in tests.

Week 4:

- Add MVP `review_diff`.
- JSON schema + Markdown output.
- Dogfood on cli-bridge's own diff.
- Record demo GIF / terminal cast.

Ship after Week 4 if:

- Fresh install works.
- `review_diff` returns useful findings on real diffs.
- `ask_all_async` avoids host timeouts.
- `usage_report` proves local control plane value.
- README tells a simple story in under 2 minutes.

## Source Index

Architecture/durability:

- https://github.com/lastmile-ai/mcp-agent
- https://docs.mcp-agent.com/mcp-agent-sdk/advanced/durable-agents
- https://github.com/langchain-ai/langgraph
- https://github.com/GitHubSecurityLab/seclab-taskflow-agent
- https://www.anthropic.com/engineering/building-effective-agents
- https://decodethefuture.org/en/ai-agent-architecture-explained/
- https://aiagentrank.io/blog/ai-agent-stack-2026
- https://www.thoughtworks.com/content/dam/thoughtworks/documents/radar/2026/04/tr_technology_radar_vol_34_en.pdf

Bridge/gateway competitors:

- https://github.com/mkXultra/ai-cli-mcp
- https://github.com/BeehiveInnovations/pal-mcp-server
- https://github.com/religa/multi_mcp
- https://briansunter.com/projects/wraptc
- https://github.com/Inebrio/Routerly
- https://portkey.ai/docs/product/ai-gateway/fallbacks
- https://klymentiev.com/blog/llm-gateway-guide
- https://www.respan.ai/ai-gateway
- https://mcp-best-practice.github.io/mcp-best-practice/best-practice/

Observability:

- https://github.com/langfuse/langfuse
- https://langfuse.com/docs/observability/overview/
- https://docs.helicone.ai/features/sessions
- https://openai.github.io/openai-agents-python/ref/tracing/

Security:

- https://mcpfw.dev/
- https://github.com/invariantlabs-ai/mcp-scan
- https://github.com/AppiumTestDistribution/secure-hulk
- https://owasp.org/www-community/attacks/MCP_Tool_Poisoning
- https://www.trailofbits.com/mcp/
- https://mcptrail.com/blog/mcp-security-best-practices/
- https://arxiv.org/abs/2602.10465

MCP prompts/elicitation:

- https://www.apollographql.com/docs/apollo-mcp-server/prompts
- https://gofastmcp.com/v2/clients/prompts
- https://fastmcp.mintlify.app/servers/elicitation
- https://github.com/cloudflare/agents/blob/main/docs/human-in-the-loop.md

Code review / consensus:

- https://github.com/calimero-network/ai-code-reviewer
- https://diffwise.app/
- https://ai-council.tech/
- https://github.com/religa/multi_mcp
- https://arxiv.org/abs/2603.16107
- https://arxiv.org/abs/2604.23088
- https://arxiv.org/abs/2605.29910
