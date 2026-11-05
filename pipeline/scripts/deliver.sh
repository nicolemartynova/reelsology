#!/bin/bash
# Platform files from a finished master, without re-rendering:
#   bash scripts/deliver.sh ../edits/11/final-master.mp4   →  next to it:
#     final-ig.mp4      Instagram + TikTok — 1080x1920
#     final-shorts.mp4  YouTube Shorts — 1440x2560 (2K: YouTube serves VP9/AV1 instead of H.264)
#
# Both: H.264 High, yuv420p BT.709 limited range (tagged), 30 fps CFR, keyframe every second,
# AAC 48 kHz 192k, moov at the front. Masters rendered before 2026-10-29 are full-range BT.601
# (yuvj420p) with 96 kHz audio — the conversion below maps them correctly; masters that are
# already BT.709 limited are passed through the same chain without a colour shift.
set -euo pipefail
IN="$1"
DIR="$(dirname "$IN")"

probe() { ffprobe -v error -select_streams "$1" -show_entries stream="$2" -of default=nw=1:nk=1 "$3" | head -1; }
PF=$(probe v pix_fmt "$IN")
RANGE=$(probe v color_range "$IN")
[ -n "$PF" ] || { echo "!! cannot read $IN"; exit 1; }
if [ "$PF" = "yuvj420p" ] || [ "$RANGE" = "pc" ]; then
  COLOR="in_color_matrix=bt601:in_range=full:out_color_matrix=bt709:out_range=limited"
else
  COLOR="in_color_matrix=bt709:in_range=limited:out_color_matrix=bt709:out_range=limited"
fi
TAGS=(-colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv)
BSF=(-bsf:v h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0)
AUDIO=(-ar 48000 -ac 2 -c:a aac -b:a 192k)

encode() { # out width height level maxrate
  ffmpeg -v error -y -i "$IN" -map 0:v:0 -map 0:a:0 \
    -vf "scale=$2:$3:flags=lanczos+accurate_rnd+full_chroma_int:$COLOR,format=yuv420p,fps=30" \
    -c:v libx264 -preset slow -crf 15 -profile:v high -level "$4" -g 30 -keyint_min 30 -bf 2 \
    -maxrate "$5" -bufsize "$5" "${TAGS[@]}" "${BSF[@]}" "${AUDIO[@]}" -movflags +faststart "$DIR/$1"
  # --platform adds the keyframe-every-second check on top of colour / audio / faststart
  python3 "$(dirname "$0")/check.py" --platform "$DIR/$1" || exit 1
  echo "→ $DIR/$1 ($(du -h "$DIR/$1" | cut -f1))"
}

encode final-ig.mp4 1080 1920 4.1 20M
encode final-shorts.mp4 1440 2560 5.1 35M
