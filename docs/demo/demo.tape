# vhs demo.tape → the README's demo.gif (https://github.com/charmbracelet/vhs)
#
# Prereqs:
#   sh setup.sh                  # creates /tmp/demo-authz (committed auth bypass)
#   cli-bridge on PATH           # uv tool install cli-bridge-mcp
#   at least two free lanes logged in (run `cli-bridge doctor`)
#
# Notes:
#   - Pacing: PlaybackSpeed 1.0 — real time. The non-streaming review wait is cut with
#     Hide/Show instead of speeding everything up; the report payoff holds 14s.
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
Set TypingSpeed 30ms
Set PlaybackSpeed 1.0
Set Theme "Catppuccin Mocha"

Hide
# Disable two lanes for a reliable demo: gemini's free tier is spent (silent empty) and Mistral
# straggles. The remaining council (claude/gpt/opencode/ollama) still catches the bypass.
Type "export CLI_BRIDGE_STATE_DB=/tmp/demo-state.sqlite CLI_BRIDGE_TRACE_FOOTER=off CLI_BRIDGE_GEMINI_ENABLED=false CLI_BRIDGE_MISTRAL_ENABLED=false && cd /tmp/demo-authz && clear"
Enter
Sleep 1s
Show

Type "# someone committed an auth bypass. would YOUR reviewer catch it?"
Enter
Sleep 1.5s
Type "git diff HEAD~1 auth.py"
Enter
# hold: the viewer needs time to spot `if user is None: return True`
Sleep 9s

Type "clear"
Enter
Sleep 500ms
Type "# one command — several AI models (different vendors) review it in parallel."
Enter
Sleep 1.5s
Type "cli-bridge security-review --base HEAD~1"
Enter
# show it genuinely starts…
Sleep 3s
# …cut the non-streaming wait (nothing prints until every lane finishes; generous margin)
Hide
Sleep 45s
Show
# payoff: hold the merged severity-ranked report long enough to read the top finding
Sleep 14s

Type "clear"
Enter
Sleep 500ms
Type "# no API keys, local-only log, $0 on the free lanes — the receipts:"
Enter
Sleep 1s
Type "cli-bridge usage --since 10m"
Enter
Sleep 7s
