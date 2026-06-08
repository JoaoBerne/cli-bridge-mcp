#!/bin/sh
# Render both demo tapes to crisp, retina-safe GIFs.
#
#   vhs <tape>  →  .mp4 at 2x (Width/Height/FontSize doubled)
#   ffmpeg      →  PNG frames at a low GIF-friendly fps
#   gifski      →  downscaled, high-quality GIF (sharp; no banding)
#
# Direct 1x GIF out of vhs was blurry on retina/mobile — the fix is resolution, not format.
#
# Usage:  sh render.sh           (from docs/demo/, with `cli-bridge` on PATH + lanes logged in)
# Deps:   vhs · ffmpeg · gifski  (brew install vhs ffmpeg gifski)
set -e
cd "$(dirname "$0")"
sh setup.sh

FPS=12
WIDTH=1600
FRAMES=/tmp/vhsframes

render() {
  tape="$1"; mp4="$2"; gif="$3"
  echo "→ $tape (live — spends a little quota)"
  vhs "$tape"
  rm -rf "$FRAMES"; mkdir -p "$FRAMES"
  ffmpeg -y -i "$mp4" -vf "fps=$FPS" "$FRAMES/f_%04d.png" -hide_banner -loglevel error
  gifski --fps "$FPS" --width "$WIDTH" --quality 90 -o "$gif" "$FRAMES"/f_*.png
  rm -f "$mp4"; rm -rf "$FRAMES"
  ls -la "$gif"
}

render demo.tape   demo.mp4   ../../assets/demo.gif
render borrow.tape borrow.mp4 ../../assets/demo-borrow.gif
echo "done."
