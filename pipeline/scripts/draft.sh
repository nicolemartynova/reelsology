#!/bin/bash
# A quick DRAFT to review animation and timing before the master: half resolution (540x960), JPEG
# frames, heavier compression, voice as is (no loudnorm passes). ~3x faster than `npm run master`,
# ~10-30 MB. One pass with sound — fine for review; the master keeps its chunked, muted-video +
# separate-wav pipeline (see master.sh) for the delivered file.
set -e
cd "$(dirname "$0")/.."
npx remotion render MyComp out/draft.mp4 --scale=0.5 --image-format=jpeg --jpeg-quality=70 --crf=30 \
  --audio-bitrate=96k --timeout=120000 --concurrency=${CONCURRENCY:-8}
ls -lh out/draft.mp4 | awk '{print "→ out/draft.mp4", $5}'
