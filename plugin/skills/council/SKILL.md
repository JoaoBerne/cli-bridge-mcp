---
name: council
description: Ask several other AI CLIs (Gemini, GPT, Mistral, opencode, Ollama…) the same question in parallel and compare their answers — a second opinion from models outside Claude.
---

# Council — parallel second opinions

Consult the cli-bridge council on the user's question.

1. If the question references files or a diff, pass the project path via the `cwd`
   argument — never paste file contents into the task (the delegates read the files
   themselves; inlining wastes tokens).
2. Call the `ask_all` MCP tool (server `cli-bridge`) with the question as `task`.
   Add `synthesize: true` when the user wants one merged answer rather than the
   side-by-side responses.
3. Free lanes only by default. Include paid/limited lanes (`include_paid: true`)
   only when the user asks for "the best" — their cost profile may refuse it.
4. Show the user each delegate's answer (or the recap line per lane), then your own
   synthesis: where the models agree, where they disagree, and what you'd do.

If `ask_all` reports no lanes installed, run the `doctor` tool and relay its
install hints instead of failing silently.
