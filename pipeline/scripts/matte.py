#!/usr/bin/env python3
"""Cut the person out of the first N frames of the cut → public/cut/NNNN.png (0-based = the
composition frame). That cutout is what puts the opening poster BEHIND the head.

    python3 scripts/matte.py N [workers]        # N = TITLE_OUT in Composition.tsx → frames 0..N-1
    python3 scripts/matte.py A-B [workers]      # any range of composition frames A..B-1

rembg birefnet-portrait on the CPU: ~8 s/frame, 2 workers ≈ 6 frames/min, so a 6-second poster
(180 frames) is ~30 min — start it FIRST and write the composition while it runs. Don't render
stills meanwhile, they starve it. Skips frames that already exist, so it can be re-run after a
restart. Other mattes are worse here: macOS Vision keeps wall patches between hair strands, and
isnet-general-use drags objects on the wall into the cutout.
"""
import glob, os, subprocess, sys
from multiprocessing import Pool

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the Remotion project
A, _, B = sys.argv[1].rpartition("-")
A, B = int(A or 0), int(B)
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 1
frames = os.path.join(here, "out", "matte-frames")
dst = os.path.join(here, "public", "cut")
os.makedirs(frames, exist_ok=True)
os.makedirs(dst, exist_ok=True)

# ONE birefnet-portrait session on CPU peaks at ~11.4 GB RSS (measured). Workers multiply that:
# 8 workers rebooted a 24 GB Mac twice. Keep 1 worker — onnxruntime already uses every core.
session = None


def init():
    global session
    from rembg import new_session
    # CPU only: onnxruntime's CoreML provider hangs for good compiling this 1 GB model
    session = new_session("birefnet-portrait", providers=["CPUExecutionProvider"])


def matte(path):
    from PIL import Image
    from rembg import remove
    out = os.path.join(dst, os.path.basename(path))
    if not os.path.exists(out):
        remove(Image.open(path), session=session).save(out + ".tmp.png")
        os.replace(out + ".tmp.png", out)  # atomic: a killed worker never leaves half a file
    return out


if __name__ == "__main__":
    # the frames at the composition's size, so the cutout maps 1:1 onto the video's object-fit.
    # Rendered by Remotion itself (the FootageOnly composition), NOT exported with ffmpeg: the two
    # convert the footage's colour differently, and an ffmpeg-made cutout makes the face jump in
    # tone (~5 L*) every time the cutout switches on or off. Same composition frames = the cutout
    # matches the picture by construction, also on a sped-up cut (rounding source frame numbers
    # put the mask off on 31 frames of one video).
    todo = [os.path.join(frames, f"{k:04d}.png") for k in range(A, B)]
    if not all(map(os.path.exists, todo)):
        subprocess.run(["npx", "remotion", "render", "FootageOnly", frames, "--sequence", "--image-format=png",
                        f"--frames={A}-{B - 1}", "--timeout=120000", "--concurrency=4"], cwd=here, check=True)
        for p in glob.glob(os.path.join(frames, "element-*.png")):
            k = int(os.path.basename(p)[len("element-"):-4])
            os.replace(p, os.path.join(frames, f"{k:04d}.png"))
    with Pool(WORKERS, initializer=init) as pool:
        for i, out in enumerate(pool.imap_unordered(matte, todo), 1):
            print(f"{i}/{len(todo)} {os.path.basename(out)}", flush=True)
    print(f"→ public/cut/: {len(glob.glob(os.path.join(dst, '*.png')))} cutouts")
