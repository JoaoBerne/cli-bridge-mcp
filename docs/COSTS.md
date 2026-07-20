# What the lanes really cost — sourced, dated, honest

This file is the source of truth behind every cost tier cli-bridge displays. **Nothing here is
detected from your account.** These are published-plan facts, verified against vendor pages in
**June 2026** by adversarial multi-source research. This space churns within weeks (one free
tier died in 48 hours in April 2026) — treat every number as a dated snapshot, re-check the
linked source before relying on it, and override any lane with `CLI_BRIDGE_<LANE>_COST`.

Anything we could not confirm from a primary source is marked **UNCONFIRMED** — explicitly not
guessed.

Three exhaustion behaviours matter more than sticker price:

| Pattern | What happens at the limit | Who does it |
|---|---|---|
| **Hard stop** | HTTP 429 / refusal — impossible to be billed | Groq, Cerebras, GitHub Models, OpenRouter `:free`, Anthropic plans |
| **Metered overage** | Usage keeps working and starts costing money/credits | GitHub Copilot (since 2026-06-01), opt-in API credits |
| **Silent downgrade** | Requests keep working on a weaker model | Google (falls back toward Flash-Lite) |

---

## 1. Genuinely free ($0, card-free where stated) — verified 2026-06

### BYO-API curl lanes (the backbone of the $0 council — see `examples/free-apis.json`)

| Provider | Free models (June 2026) | Limits | Card? | Exhaustion | Source |
|---|---|---|---|---|---|
| **Groq** | llama-3.3-70b-versatile · llama-3.1-8b-instant · gpt-oss-120b/20b | 70b: 30 RPM / 1k RPD; 8b: 30 RPM / 14.4k RPD; gpt-oss: 30 RPM / 1k RPD | No | Hard stop (429) | [console.groq.com/docs/rate-limits](https://console.groq.com/docs/rate-limits) |
| **Cerebras** | gpt-oss-120b · zai-glm-4.7 | 5 RPM / 30K tokens/min / 1M tokens/day each; free-tier context 65k (gpt-oss-120b) / 64k (zai-glm-4.7) vs 131k paid | No | Hard stop (429) | [inference-docs.cerebras.ai/support/rate-limits](https://inference-docs.cerebras.ai/support/rate-limits) |
| **GitHub Models** | many (OpenAI-compatible endpoint) | "All GitHub accounts have rate-limited access at no cost"; limits vary by model & Copilot plan | No (PAT) | Hard stop ("usage is blocked") | [docs.github.com](https://docs.github.com/billing/managing-billing-for-your-products/about-billing-for-github-models) |
| **OpenRouter** | `:free` variants (~24) · `openrouter/free` random router | **UNCONFIRMED** — official docs render template placeholders; secondary sources disagree (50–1000 RPD) | No | Hard stop | [openrouter.ai/docs/faq](https://openrouter.ai/docs/faq) |

### Vendor CLIs with a free login tier

| CLI | Status June 2026 | Detail |
|---|---|---|
| **Gemini CLI → Antigravity (`agy`)** | ⚠️ **Consumer tiers DEAD since 2026-06-18** | Gemini CLI's free/Pro/Ultra consumer access stopped 2026-06-18 ([Google official](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)); the old `gemini` binary now serves only **paid API keys / enterprise licenses**. The lane auto-falls back to **Antigravity (`agy`)** — its free tier is real (no card) but **scarce: ~20 agent req/day** (cut from 250 at launch; exact current figure **UNCONFIRMED**, secondary sources), refreshing ~5h. So cli-bridge degrades this lane to **`limited`** post-sunset (free in $, but quota too small for fan-out), not `free`. |
| **Qwen Code** | ❌ **DEAD** | OAuth free tier cut 1000→100 RPD on 2026-04-13, fully closed 2026-04-15 ([issue #3203](https://github.com/QwenLM/qwen-code/issues/3203) + official docs). Only metered API keys work now — hence the lane's `paid` default. |
| **Codex CLI** | Headless confirmed; $0 tier **UNCONFIRMED** | `codex exec` is officially supported for scripts/CI. Codex is included on **all ChatGPT plans incl. Free/Go** (plan-scaled quotas) — but OpenAI labels the Free/Go inclusion a **limited-time promotion** (no published end date), and a card-free $0 login path was not confirmed by primary sources. ⚠ **The plan also caps WHICH MODELS you may select, and no vendor page states this.** Verified live 2026-07-20 on a `chatgpt`-auth Codex: `-m gpt-5.6-sol` (the GPT-5.6 flagship) is refused with *"not supported when using Codex with a ChatGPT account"* — and a **fabricated** model id returns the *identical* message, so that error is an entitlement gate, not a name check. Don't read it as "no such model". To see the set your plan *does* allow (Codex exposes no `models` subcommand), read the list Codex itself caches from the server: `~/.codex/models_cache.json` → each entry's `slug`, `description` and `supported_reasoning_levels`. Undocumented internal file, so treat it as a diagnostic, not an API. |
| **Mistral Vibe** | Free tier works in practice | No surviving primary-source claim on exact quotas — **UNCONFIRMED** limits; hence the lane's conservative `limited` default (override to `free` if you're on the free tier). |
| **Cursor CLI** (`cursor-agent`) | Hobby tier is card-free; limits **UNPUBLISHED** | No fixed quota is stated on the current [pricing page](https://cursor.com/pricing); every prompt burns request-equivalent credits on a metered model (Pro $20 / Pro+ $60 / Ultra $200) — hence the lane's conservative `limited` default. Headless via `-p`; ⚠️ a bare `-p` has **full tool access (write + shell)**, so the lane's read-only gate is `--mode plan`. Flags verified live 2026-07 (v2026.07.16). |
| **Apple Foundation Models** (`fm`) | ✅ **$0, no account, no network** | On-device inference on a Mac with Apple Intelligence enabled. `fm quota-usage` states the quota applies to **PCC only**, so the on-device model is unmetered — the lane's `free` default is a measured fact, not a plan reading. Verified live 2026-07: strong perception (it transcribed a test image more accurately than the cloud lanes), weak reasoning (small model). **PCC** (`applepcc`) is also $0 but metered, and is refused in any spawned subprocess — *"PCC inference is not available in this context"* even unsandboxed — so it is reached over HTTP through an `fm serve` **you** start; the gate is session attribution, not permissions. |
| **Grok CLI** | No free tier | Requires SuperGrok / X Premium+. Headless via `-p`. |
| **opencode (built-in free models)** | $0, pattern-discovered | See gateway section below — names churn fast, which is why cli-bridge discovers `opencode/*-free` live and never pins a name. |
| Copilot CLI / Cline / Aider / Goose / Amazon Q / Cursor / Windsurf | **UNCONFIRMED** | Zero claims survived adversarial verification (the popular "Copilot Free 15/150 RPD" figures were *refuted* 0-3). |

### Gateways

**opencode Zen free models** (June 2026: Big Pickle, DeepSeek V4 Flash Free, MiMo-V2.5 Free,
Nemotron 3 Ultra Free — $0/$0): real, but (a) "during its free period, collected data may be
used to improve the model" (official), (b) the documented Zen onboarding asks for billing
details, so it is **not cleanly card-free**, and (c) the list churns fast. The opencode CLI's
*built-in* default free models work without an API key; that path was not independently
card-verified.

---

## 2. Metered API pricing (per 1M tokens, June 2026) — for `CREDITS_PER_1K` and "is paid worth it?"

Anchor: **a typical code review ≈ 3k input + 1k output tokens.**

| Model | $/1M in | $/1M out | ~$/review (3k/1k) | Source |
|---|---|---|---|---|
| Claude Opus 4.8 | 5.00 | 25.00 | **0.040** | [platform.claude.com](https://platform.claude.com/docs/en/about-claude/pricing) |
| GPT-5.6 Sol | 5.00 | 30.00 | 0.045 | [developers.openai.com](https://developers.openai.com/api/docs/models/gpt-5.6-sol) *(added 2026-07-20)* |
| GPT-5.5 | 5.00 | 30.00 | 0.045 | [developers.openai.com](https://developers.openai.com/api/docs/pricing) |
| Claude Sonnet 4.6 | 3.00 | 15.00 | 0.024 | platform.claude.com |
| GPT-5.6 Terra | 2.50 | 15.00 | 0.023 | developers.openai.com *(added 2026-07-20)* |
| GPT-5.4 | 2.50 | 15.00 | 0.023 | developers.openai.com |
| GPT-5.6 Luna | 1.00 | 6.00 | 0.009 | developers.openai.com *(added 2026-07-20)* |
| Gemini 3.1 Pro Preview | 2.00 | 12.00 | 0.018 | [ai.google.dev](https://ai.google.dev/gemini-api/docs/pricing) |
| Gemini 3.5 Flash | 1.50 | 9.00 | 0.014 | ai.google.dev |
| Gemini 2.5 Pro | 1.25 | 10.00 | 0.014 | ai.google.dev |
| Grok 4.3 (cheapest flagship) | 1.25 | 2.50 | 0.0063 | [docs.x.ai](https://docs.x.ai/developers/models/grok-4.3) |
| Claude Haiku 4.5 | 1.00 | 5.00 | 0.008 | platform.claude.com |
| GLM 5.1 (via OpenRouter) | 0.98 | 3.08 | 0.0060 | openrouter.ai |
| Mistral Large 3 (flagship!) | 0.50 | 1.50 | 0.003 | [mistral.ai/pricing](https://mistral.ai/pricing/) |
| DeepSeek V4-pro | 0.435 | 0.87 | 0.0022 | [api-docs.deepseek.com](https://api-docs.deepseek.com/quick_start/pricing) |
| Mistral Devstral 2 | 0.40 | 2.00 | 0.0032 | mistral.ai/pricing |
| **DeepSeek V4-flash** | **0.14** | **0.28** | **0.0007 (~57× cheaper than Opus)** | api-docs.deepseek.com |
| Gemini 2.5 Flash-Lite | 0.10 | 0.40 | 0.0007 | ai.google.dev |
| Mistral Devstral Small 2 | 0.10 | 0.30 | 0.0006 | mistral.ai/pricing |
| Groq · llama-3.1-8b | 0.05 | 0.08 | 0.0002 | [groq.com/pricing](https://groq.com/pricing) |
| Groq · gpt-oss-120b | 0.15 | 0.60 | 0.0011 | groq.com/pricing |

Suggested `CLI_BRIDGE_<LANE>_CREDITS_PER_1K` (1 credit = $0.01, blended 3:1 in:out from the
table — honest estimates, not vendor truth): Opus 4.8 ≈ `1.0` · GPT-5.5 ≈ `1.1` · Sonnet ≈
`0.6` · Grok 4.3 ≈ `0.16` · Mistral Large 3 ≈ `0.075` · DeepSeek V4-flash ≈ `0.018`.

Levers that change the real bill:

- **Prompt caching** — Anthropic: cache hit = 10 % of input (writes 1.25×/2×); OpenAI &
  DeepSeek: −90 % on cached input.
- **Batch API** — −50 % in and out on Anthropic and Alibaba/Qwen; stacks with caching.
- **Context tiering** — Gemini Pro and Qwen roughly **double** rates above ~200–256k tokens.
- **OpenRouter** — pass-through with no markup on spot-checked models (GPT-5.5, Grok 4.3,
  GLM 5.1), but *not* uniformly (its DeepSeek display diverges from direct rates) — check the
  model's own OpenRouter page.
- DeepSeek legacy aliases (`deepseek-chat`, `deepseek-reasoner`) **die 2026-07-24** — use
  `deepseek-v4-flash` / `-pro`.

**UNCONFIRMED**: Cerebras/Together/Fireworks/SambaNova hoster rates; Kimi K2.6; Claude
subscription→API overage exact rates; Codex credit (1 = $0.01) hors-plan mechanics; opencode
Zen per-model rates and its reported $20 minimum.

---

## 3. Subscriptions (flat plans) — June 2026

*Salvaged from a research run whose adversarial-verification stage crashed: facts below are
fetch-confidence (primary pages read) but **not adversarially verified** — slightly lower
confidence than sections 1–2.*

| Plan | What the CLI gets | Exhaustion | Notes |
|---|---|---|---|
| **Claude Pro/Max** | Claude Code shares **one bucket** with chat | Hard stop (+ opt-in API credits) | Scripting via the *official CLI* is permitted; third-party reuse of subscription tokens was **banned 2026-04-04** — exactly the line cli-bridge's ban-safe design never crosses. |
| **ChatGPT (all plans incl. Free)** | Codex included, plan-scaled quotas from a **shared agentic pool** | Pooled limits; documented quota downgrades Apr 2026 | The reason `gpt` defaults to `limited`, not `paid`. |
| **Google AI Pro / Ultra → Antigravity** | Gemini CLI access ended 2026-06-18 (incl. paid tiers); Pro/Ultra now run through **Antigravity** ($20 / $100-$200/mo) | Credit/quota model, refreshes ~5h | The free `agy` tier (~20 req/day) is why the gemini lane degrades to `limited`. |
| **GitHub Copilot** | CLI access per plan | **Usage-based credits since 2026-06-01** — can meter, not stop | |
| **Alibaba Coding Plan (Qwen)** | cheap flat quota — **but its ToS prohibits non-interactive use** | — | A Coding Plan is therefore **not a valid path for cli-bridge** (which is non-interactive by nature). Script-legal path = metered API key. |
| **opencode Go ($10/mo)** | prepaid credits | Caps: $12/5h · $30/wk · $60/mo | |
| **xAI SuperGrok / X Premium+** | required for Grok CLI | **UNCONFIRMED** quotas (no primary page fetched) | |
| **Mistral paid plans** | — | **UNCONFIRMED** (no primary page fetched) | |

---

*Maintained by hand. If a number here disagrees with the vendor page you just read, the vendor
page wins — please file an issue with the link.*
