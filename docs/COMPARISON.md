# CLI comparison — what each lane is actually best at

> **Snapshot: 2026-06-08.** This space churns in *weeks* (a free tier once died in 48h; Gemini's
> personal CLI is renamed to Antigravity on 2026-06-18). Treat this as **directional** — verify
> against each vendor's current docs before relying on it. Items marked ⚗️ are beta / not verified
> live by cli-bridge.

**Mental model.** Each CLI is a **harness** (the loop that reads your files and calls tools) **+** a
**model** **+** its **capabilities**. The model thinks; the harness drives; they're separable. Each
vendor optimised a *different* axis — which is exactly why combining them pays off.

| CLI (lane) | Best at / what it does uniquely | Real limit |
|---|---|---|
| **Claude Code** (`claude`) | Strongest tooled reasoning; a programmable platform — subagents (parallel delegation), hooks (deterministic enforcement), reusable skills | subagents are **same-family** (self-confirmation), and tied to one machine / one checkout |
| **Codex** (`gpt`) | Image generation (`gpt-image-2`, **no API key** — paid ChatGPT plan, not Free); the strongest sandboxing (container by default); ~1M-token context (GPT‑5.5 default since 2026-04) | quotas shared with your ChatGPT plan |
| **Gemini** (`gemini` / `agy`) | 1M-token context; Google-Search grounding; web fetch; free 1000 req/day; image gen via the official Nano Banana extension (needs a separate Gemini API key) ⚗️ | personal CLI moves to **Antigravity on 2026-06-18** (the `agy` lane already covers it); no official video extension (Veo = paid API only) |
| **Grok** (`grok`) ⚗️ | Real-time X + web data via xAI's server-side search tools (must be enabled); context up to 1M (grok‑4.3) — the CLI's grok‑build‑0.1 is 256k; video (Imagine) | CLI is **beta** (needs SuperGrok or X Premium+; no free tier) |
| **Qwen Code** (`qwen`) ⚗️ | Open source; self-hostable locally via Ollama (offline, $0); strong agentic coding | below the top proprietary models on the hardest tasks |
| **opencode** (`opencode`) | Terminal-first, open source; 75+ providers via Models.dev, local models, LSP, multi-session — the most model-flexible | no model of its own; lost the Claude Pro/Max login after a dispute with Anthropic |
| **Ollama** (`ollama`) | Fully local, $0, offline, private | quality + speed bounded by your own hardware |

## The composite — what cli-bridge gives you

The capability envelope becomes the **union**. You drive a single assistant whose ceiling on *each*
axis is the ecosystem's best — not the limit of whichever tool you happened to open this morning:

- **code** with the strongest model for the task (route to Claude / Codex / Qwen),
- **read ~1M tokens** (Gemini / Codex / Grok) when your own context is too short,
- answer with **fresh knowledge** (Gemini's Search grounding, Grok's X/web search tools) past a stale cutoff,
- **generate** images (Codex; Gemini via extension) and video (Grok Imagine ⚗️), **see** screenshots (Gemini),
- fall back to a **free or local** lane (Gemini free tier, Qwen / Ollama) when you're capped or cost-bound,
- **spread** the load across the subscriptions you already pay for — no single quota wall.

**The emergent property no single CLI has: true cross-vendor control.** Claude Code has subagents,
Grok has parallel subagents — but they're all the *same family*, so they're condemned to
self-confirmation. The composite is the only one that can put a **different vendor** in the
reviewer's seat. No CLI can do that internally, by construction — it's the moat.

## The honest seam — orchestrated, not fused

cli-bridge unites **capabilities, not mind**. Be clear-eyed about what it is *not*:

- **No shared memory.** Each lane is a stateless spawn — it sees only your session/the others' work
  to the extent you (or the host) pass it along. Cross-vendor lanes are fully separate processes.
- **Spawn latency + cost.** It's not one hot, unified agent.
- **Uneven quality.** Union of *capabilities* ≠ uniform quality; a free-lane answer is not an Opus answer.
- **The host always drives.** This is orchestration, not fusion. You conduct an orchestra of
  specialists; you don't get one brain that has every power. (The "single brain / bus between AIs"
  is precisely the vaporware we deferred on purpose — see [ARCHITECTURE.md](ARCHITECTURE.md).)

> **Lane abstraction as insurance.** When a vendor renames or retires a CLI (e.g. Gemini → Antigravity
> on 2026-06-18), you swap the lane and your workflow is unchanged. The `agy` lane already covers that
> one — the abstraction is the point.

## Experimental lanes — verified invocations (⚗️)

The ⚗️ lanes are **not run live by cli-bridge's test suite**, so they stay flagged experimental. The
headless invocation each lane builds was, however, **verified against the vendor's official docs
(2026-06)** — it's the documented non-interactive command, not a guess. Run `cli-bridge doctor --deep`
to check the flags against the installed CLI's `--help` and warn on drift.

| Lane | Invocation cli-bridge builds | Verified against (2026-06) |
|---|---|---|
| `copilot` | `copilot -p "<task>"` · `--model <id>` · `--allow-all-tools` (build) | [Copilot CLI programmatic reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference) · [Allowing tools](https://docs.github.com/en/copilot/how-tos/copilot-cli/allowing-tools) |
| `qwen` | `qwen -p "<task>"` · `-m <id>` · `--yolo` (build) | [Qwen Code — Headless mode](https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/) |
| `grok` | `grok -p "<task>"` · `--model <id>` (best-effort) | [Grok Build Beta](https://x.ai/cli) · install `curl -fsSL https://x.ai/cli/install.sh \| bash` |

> Verified = the **flags exist and are documented**; it does **not** mean cli-bridge has exercised the
> full path end-to-end on these lanes. `--model` on `grok` stays best-effort (the flag set churns in
> beta). Build/write flags (`--allow-all-tools`, `--yolo`) grant the delegate your own filesystem
> access — opt-in, same as every other build lane.
