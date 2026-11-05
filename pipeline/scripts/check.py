#!/usr/bin/env python3
"""Technical check of a video file against the delivery standard. Exit code = number of failures.

    python3 scripts/check.py out/final-master.mp4
    python3 scripts/check.py --platform edits/9/final-ig.mp4    # + keyframe every second

Everything checked here is invisible in QuickTime, which forgives all of it — and every item broke
a published video at least once: 96 kHz audio played as silence, full-range BT.601 shifted colour
and skin, a moov at the end made the upload look broken, sparse keyframes multiplied artefacts.

Reads tags the way the platforms do (ffprobe on the stream), so a file that is right is never
rejected for an untagged-but-default value — the first version of the deliver check failed good
files that way.
"""
import json, struct, subprocess, sys

args = [a for a in sys.argv[1:] if not a.startswith("--")]
PLATFORM = "--platform" in sys.argv
path = args[0]


def probe(*entries):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", ",".join(entries), "-of", "json", path],
                         capture_output=True, text=True).stdout
    return json.loads(out or "{}")


def moov_first():
    """Walk the top-level MP4 boxes: is moov before mdat (faststart)?"""
    with open(path, "rb") as f:
        while True:
            head = f.read(8)
            if len(head) < 8:
                return False
            size, kind = struct.unpack(">I4s", head)
            if kind == b"moov":
                return True
            if kind == b"mdat":
                return False
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0] - 8
            elif size == 0:
                return False
            f.seek(size - 8, 1)


info = probe("stream=codec_type,codec_name,profile,pix_fmt,color_range,color_space,color_primaries,"
             "color_transfer,r_frame_rate,avg_frame_rate,sample_rate,channels,width,height")
v = next((s for s in info.get("streams", []) if s["codec_type"] == "video"), None)
a = next((s for s in info.get("streams", []) if s["codec_type"] == "audio"), None)
if not v:
    sys.exit(f"!! {path}: no video stream")

checks = [
    ("video codec", v.get("codec_name"), v.get("codec_name") == "h264"),
    ("pixels", v.get("pix_fmt"), v.get("pix_fmt") == "yuv420p"),
    ("range", v.get("color_range"), v.get("color_range") == "tv"),
    ("matrix", v.get("color_space"), v.get("color_space") == "bt709"),
    ("primaries", v.get("color_primaries"), v.get("color_primaries") == "bt709"),
    ("transfer", v.get("color_transfer"), v.get("color_transfer") == "bt709"),
    ("fps", v.get("r_frame_rate"), v.get("r_frame_rate") == "30/1" and v.get("avg_frame_rate") == "30/1"),
    ("audio", a and a.get("codec_name"), bool(a) and a.get("codec_name") == "aac"),
    ("sample rate", a and a.get("sample_rate"), bool(a) and a.get("sample_rate") == "48000"),
    ("channels", a and a.get("channels"), bool(a) and a.get("channels") == 2),
    ("faststart", "moov first" if moov_first() else "moov at the end", moov_first()),
]
if PLATFORM:
    kf = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-skip_frame", "nokey",
                         "-show_entries", "frame=pts_time", "-of", "csv=p=0", path],
                        capture_output=True, text=True).stdout.split()
    times = [float(t.strip(",")) for t in kf if t.strip(",")]
    gap = max((b - a for a, b in zip(times, times[1:])), default=0)
    checks.append(("keyframes", f"max gap {gap:.2f}s", gap <= 1.01))

bad = 0
print(f"{path}  {v.get('width')}x{v.get('height')}")
for name, value, ok in checks:
    bad += not ok
    print(f"  {'ok' if ok else '!!'}  {name:<12} {value}")
print("  → meets the delivery standard" if not bad else f"  → {bad} problem(s): do NOT upload this file")
sys.exit(bad)
