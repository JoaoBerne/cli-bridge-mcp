# vhs demo.tape → the README's demo.gif (https://github.com/charmbracelet/vhs)
#
# Prereqs:
#   sh setup.sh                  # creates /tmp/demo-authz (committed auth bypass)
#   cli-bridge on PATH           # uv tool install cli-bridge-mcp
#   at least two free lanes logged in (run `cli-bridge doctor`)
#
# Notes:
#   - Lanes are auto-detected; hide any flaky one with CLI_BRIDGE_<LANE>_ENABLED=false.
#   - CLI_BRIDGE_STATE_DB points at a scratch file so `usage` shows only this demo's runs.
#   - Plain Sleeps (not Wait): vhs's Wait+Screen misses matches on long scrolled bursts.
#   - Rendered to .mp4 at 2x (Width/Height/FontSize doubled), then encoded to a crisp GIF with
#     gifski (see render.sh) — direct GIF at 1x was blurry on retina/mobile.
Output demo.mp4
Set Shell "bash"
Set FontSize 28
Set Width 2400
Set Height 1600
Set TypingSpeed 35ms
Set PlaybackSpeed 2.2
Set Theme "Catppuccin Mocha"

Hide
# Disable two lanes for a snappy demo: gemini's free tier is spent (silent empty) and one Mistral
# call straggled to 70s today. The remaining council (claude/gpt/opencode/ollama) still catches it.
Type "export CLI_BRIDGE_STATE_DB=/tmp/demo-state.sqlite CLI_BRIDGE_TRACE_FOOTER=off CLI_BRIDGE_GEMINI_ENABLED=false CLI_BRIDGE_MISTRAL_ENABLED=false && cd /tmp/demo-authz && clear"
Enter
Sleep 1s
Show

Type "# a committed auth bypass — can your reviewer catch it?"
Enter
Type "git diff HEAD~1 auth.py"
Enter
Sleep 6s

Type "clear"
Enter
Sleep 500ms
Type "# one command — several AI models review it in parallel, findings merged + severity-ranked"
Enter
Type "cli-bridge security-review --base HEAD~1"
Enter
# security-review is non-streaming: nothing prints until every lane finishes. Sleep must comfortably
# exceed the slowest lane (~14s here) or the next command gets typed over a still-running review.
Sleep 24s

Type "clear"
Enter
Sleep 500ms
Type "# zero API keys, local-only log, $0 on free lanes — receipts:"
Enter
Type "cli-bridge usage --since 5m"
Enter
Sleep 8s
