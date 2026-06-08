# vhs borrow.tape → the README's "borrow" demo (assets/demo-borrow.gif)
# https://github.com/charmbracelet/vhs
#
# Prereqs:
#   sh setup.sh                  # creates /tmp/demo-build
#   cli-bridge on PATH           # uv tool install cli-bridge-mcp
#   one build-capable lane logged in (opencode/gpt/…) — run `cli-bridge doctor`
#
# Rendered at 2x (Width/Height/FontSize doubled) so it stays crisp on retina/mobile.
Output borrow.mp4
Set Shell "bash"
Set FontSize 28
Set Width 2400
Set Height 1600
Set TypingSpeed 35ms
Set PlaybackSpeed 2.0
Set Theme "Catppuccin Mocha"

Hide
Type "export CLI_BRIDGE_STATE_DB=/tmp/demo-state.sqlite CLI_BRIDGE_TRACE_FOOTER=off && cd /tmp/demo-build && clear"
Enter
Sleep 1s
Show

Type "# borrow ANOTHER model to do real work — safely."
Enter
Type "# it builds in a throwaway worktree; you get a DIFF back, your repo is never touched."
Enter
Sleep 1s
Type "cli-bridge build opencode 'add a subtract(a, b) function with a docstring to calc.py'"
Enter
Sleep 18s

Type "clear"
Enter
Type "# proof: your real repo was never modified —"
Enter
Type "git status --short ; echo '<clean — nothing staged, nothing changed>'"
Enter
Sleep 6s
