# vhs borrow.tape → the README's "borrow" demo (assets/demo-borrow.gif)
# https://github.com/charmbracelet/vhs
#
# Prereqs:
#   sh setup.sh                  # creates /tmp/demo-build
#   cli-bridge on PATH           # uv tool install cli-bridge-mcp
#   one build-capable lane logged in (opencode/gpt/…) — run `cli-bridge doctor`
#
# Pacing: PlaybackSpeed 1.0 — real time, viewers must be able to READ the diff. The dead
# build wait is cut with Hide/Show instead of speeding everything up; payoff frames hold 10s+.
# Rendered at 2x (Width/Height/FontSize doubled) so it stays crisp on retina/mobile.
Output borrow.mp4
Set Shell "bash"
Set FontSize 28
Set Width 2400
Set Height 1600
Set TypingSpeed 30ms
Set PlaybackSpeed 1.0
Set Theme "Catppuccin Mocha"

Hide
Type "export CLI_BRIDGE_STATE_DB=/tmp/demo-state.sqlite CLI_BRIDGE_TRACE_FOOTER=off && cd /tmp/demo-build && clear"
Enter
Sleep 1s
Show

Type "# delegate real work to ANOTHER model — safely."
Enter
Sleep 1.5s
Type "# it edits a throwaway copy of the repo; you get a reviewable DIFF back."
Enter
Sleep 2s
Type "cli-bridge build opencode 'add a divide(a, b) function that raises ValueError on b == 0, to calc.py'"
Enter
# show that the build genuinely starts…
Sleep 3s
# …then cut the dead wait (the lane works off-camera; generous so slow runs still finish)
Hide
Sleep 40s
Show
# payoff: hold the diff long enough to actually read it
Sleep 12s

Type "clear"
Enter
Sleep 500ms
Type "# and your real repo was never touched —"
Enter
Sleep 1s
Type "git status --short && echo '<clean — nothing changes until YOU apply the diff>'"
Enter
Sleep 7s
