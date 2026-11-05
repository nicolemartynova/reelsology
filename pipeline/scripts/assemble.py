#!/usr/bin/env python3
"""Join hand-picked segments of a take into one intermediate file — for edits where the joins are
chosen by meaning (multicam, best phrases from several attempts), not by pause detection.

    python3 scripts/assemble.py ../takes/1.MOV seg.json out/edit.mov

seg.json = [[start, end], …] in SOURCE seconds, in playback order. Prints the total length and the
frame of every join (the punch-in table hangs off those).

Resolution: the SOURCE resolution, always. A 4K take stays 4K — downscaling to 1080 here and then
punching in later blew up a degraded frame (the main cause of soft footage). Nothing is upscaled.
SIZE=WxH caps the size (downscale only), e.g. SIZE=1296x2304 to save disk.

Env: SPEED=1.06 (frame blending + atempo, never dropped frames), VOICE="<ffmpeg audio chain>"
(optional voice processing — the project's own, none by default), CRF=14.
Audio: PCM 48 kHz, 15 ms fades at every join so no cut clicks; loudness is left to master.sh.
"""
import json, os, subprocess, sys

src, seg_path, dst = (os.path.abspath(a) for a in sys.argv[1:4])
SEG = json.load(open(seg_path))
SPEED = float(os.environ.get("SPEED", "1"))
SIZE = os.environ.get("SIZE", "")
VOICE = os.environ.get("VOICE", "")
CRF = os.environ.get("CRF", "14")

f = []
for i, (a, b) in enumerate(SEG):
    f.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS,setsar=1[v{i}]")
    f.append(f"[0:a:0]atrim=start={a}:end={b},asetpts=PTS-STARTPTS,aresample=48000,afade=t=in:d=0.015,"
             f"afade=t=out:st={b - a - 0.015:.3f}:d=0.015[a{i}]")
n = len(SEG)
f.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[cv][ac]")

# speed 1: fps=30 only normalises a VFR phone take. Otherwise blend — dropping frames at x1.06
# stutters about twice a second.
v = "fps=30" if SPEED == 1 else f"setpts=PTS/{SPEED},framerate=fps=30"
if SIZE:
    W, H = SIZE.lower().split("x")
    v += (f",scale=w='min(iw,{W})':h='min(ih,{H})':force_original_aspect_ratio=decrease"
          f":force_divisible_by=2:flags=lanczos")
# phone takes come both limited and full range (yuvj420p): BT.709 limited, all fields tagged
f.append(f"[cv]{v},scale=out_color_matrix=bt709:out_range=limited,format=yuv420p,"
         "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv[v]")
a = ",".join(x for x in (VOICE, f"atempo={SPEED}" if SPEED != 1 else "", "aresample=48000", "aformat=channel_layouts=stereo") if x)
f.append(f"[ac]{a}[a]")

os.makedirs(os.path.dirname(dst), exist_ok=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-filter_complex", ";".join(f),
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", CRF, "-preset", "medium", "-g", "30",
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                "-c:a", "pcm_s16le", "-ar", "48000", dst], check=True)

# the joins on the OUTPUT timeline (after speed), in composition frames
total = sum(b - a for a, b in SEG) / SPEED
joins = [round(sum(b - a for a, b in SEG[:k]) / SPEED * 30) for k in range(1, n)]
res = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                      "-of", "csv=p=0:s=x", dst], capture_output=True, text=True).stdout.strip()
json.dump({"src": src, "seg": SEG, "speed": SPEED, "size": SIZE, "voice": VOICE, "crf": int(CRF), "joins": joins},
          open(os.path.splitext(dst)[0] + ".assemble.json", "w"), indent=1)
print(f"{os.path.basename(dst)}  {res}  {total:.2f}s  joins {joins}")
