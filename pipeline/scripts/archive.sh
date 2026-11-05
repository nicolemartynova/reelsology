#!/bin/bash
# Save EVERYTHING a re-render needs, next to the delivered files:
#   bash scripts/archive.sh ../edits/12            (FOOTAGE=1 also copies public/footage.mp4)
#
# Videos 1-8 of the first project could not simply be re-rendered: the exact splices and the
# cutouts were never saved, and restoring the cut took hours. With this archive a re-render is
#   KEEPS=../edits/12/project-state/keeps.json python3 scripts/cut.py
#   cp -R ../edits/12/project-state/{src,cut,captions.json,reels.config.json} back, npm run master
#
# The archive lives OUTSIDE the Remotion project (../edits, not out/ or src/): tsc and the bundler
# pick up every .ts/.tsx they find, and a backup copy inside the project broke the build once.
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="$1/project-state"
mkdir -p "$DEST"

[ -f public/keeps.json ] || { echo "!! public/keeps.json missing — the cut cannot be reproduced"; exit 1; }
cp public/keeps.json public/captions.json "$DEST/"
cp -R src "$DEST/"
# the style values the code read for THIS video (words per caption line, sizes, colours…):
# re-rendering with today's config once turned 4-word captions into 3-word ones
[ -f reels.config.json ] && cp reels.config.json "$DEST/"
[ -d public/cut ] && { rm -rf "$DEST/cut"; cp -R public/cut "$DEST/"; }
for f in out/*.assemble.json; do [ -f "$f" ] && cp "$f" "$DEST/"; done
[ "${FOOTAGE:-0}" = 1 ] && cp public/footage.mp4 "$DEST/"
for f in out/final-master.mp4 out/preview.mp4; do [ -f "$f" ] && cp "$f" "$1/"; done

echo "→ $DEST: $(ls "$DEST" | tr '\n' ' ')"
