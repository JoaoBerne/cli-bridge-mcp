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
Output demo.gif
Set Shell "bash"
Set FontSize 14
Set Width 1200
Set Height 800
Set TypingSpeed 35ms
Set PlaybackSpeed 2.5
Set Theme "Catppuccin Mocha"

Hide
Type "export CLI_BRIDGE_STATE_DB=/tmp/demo-state.sqlite CLI_BRIDGE_TRACE_FOOTER=off && cd /tmp/demo-authz && clear"
Enter
Sleep 1s
Show

Type "git log --oneline -2"
Enter
Sleep 5s

Type "git diff HEAD~1"
Enter
Sleep 8s

Type "# one command — several AI models review it in parallel, findings merged + severity-ranked"
Enter
Type "cli-bridge security-review --base HEAD~1"
Enter
Sleep 32s

Type "clear"
Enter
Type "# zero API keys, local-only log, $0 on free lanes — receipts:"
Enter
Type "cli-bridge usage --since 5m"
Enter
Sleep 14s
