#!/usr/bin/env python3
"""Download ONE reel and lay it out for a frame-by-frame reading — the raw material of a lesson.

    python3 scripts/intake.py URL_or_file [slug]
    COOKIES_FROM=chrome python3 scripts/intake.py URL      # only if Instagram demands a login (user's OK!)

Everything lands in work/<slug>/ (gitignored — other people's reels are for analysis only):
  video.mp4, meta.json        the reel and what yt-dlp knows (author, views, caption)
  analysis.md / .json         transcript by phrase with timecodes, cuts, shot lengths, speech rate,
                              loudness per second
  hook.jpg                    the first 3 s, a frame every 0.25 s
  shots-N.jpg                 the first frame of every shot, labelled with its time
  overview-N.jpg              a frame every second, labelled

Measured, not guessed (same method as the editing harness's refs.py): a picture change is a scene
score > 0.1 — a hard cut, a punch-in on a splice (~0.15-0.22), a full-frame insert; a talking head
alone sits at ~0.003, a slow push-in never registers, so read zooms and graphics off the sheets.
"""
import glob, json, os, re, shutil, statistics, subprocess, sys, tempfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.expanduser(os.environ.get("WHISPER_MODEL", "~/.cache/whisper/ggml-large-v3-turbo.bin"))
FPS = 4  # small frames kept for the sheets


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def tc(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


src = sys.argv[1]
slug = sys.argv[2] if len(sys.argv) > 2 else None
if not slug:
    base = os.path.splitext(os.path.basename(src.rstrip("/").split("?")[0]))[0]
    slug = f"{date.today()}-" + (re.sub(r"[^\w-]+", "-", base).strip("-")[:40] or "reel")
OUT = os.path.join(ROOT, "work", slug)
os.makedirs(OUT, exist_ok=True)
video = os.path.join(OUT, "video.mp4")

# ---------- 1. the reel
meta = {"src": src, "slug": slug}
if not os.path.exists(video):
    if os.path.exists(src):
        shutil.copy(src, video)
    else:
        cmd = ["yt-dlp", "-q", "--no-warnings", "-f", "mp4/bv*+ba/b", "--merge-output-format", "mp4",
               "--write-info-json", "-o", os.path.join(OUT, "video.%(ext)s"), src]
        if os.environ.get("COOKIES_FROM"):
            cmd[1:1] = ["--cookies-from-browser", os.environ["COOKIES_FROM"]]
        r = run(*cmd)
        if r.returncode or not os.path.exists(video):
            err = (r.stderr.strip().splitlines() or ["unknown error"])[-1]
            sys.exit(f"download failed: {err[:300]}\n(Instagram login wall? ask the user, then COOKIES_FROM=chrome)")
info = os.path.join(OUT, "video.info.json")
if os.path.exists(info):
    j = json.load(open(info))
    meta.update({k: j.get(k) for k in ("uploader", "uploader_id", "webpage_url", "view_count", "like_count",
                                       "comment_count", "upload_date", "description") if j.get(k) is not None})
    os.remove(info)
json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), ensure_ascii=False, indent=1)

probe = run("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video).stdout.strip()
if not re.fullmatch(r"[\d.]+", probe):
    shutil.rmtree(OUT)
    sys.exit(f"not a video: {src}")
dur = float(probe)
size = run("ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
           "-of", "csv=p=0:s=x", video).stdout.strip()

# ---------- 2. cuts and loudness, one pass
err = run("ffmpeg", "-hide_banner", "-nostats", "-i", video,
          "-vf", "scale=270:-2,select='gt(scene,0.1)',showinfo", "-af", "ebur128", "-f", "null", "-").stderr
cuts = []
for t in map(float, re.findall(r"pts_time:([\d.]+)", err)):
    if not cuts or t - cuts[-1] > 0.25:  # one splice often scores on two adjacent frames
        cuts.append(t)
edges = [0.0] + cuts + [dur]
shots = [(a, b) for a, b in zip(edges, edges[1:]) if b - a > 0.05]
lens = [b - a for a, b in shots]
# ebur128 prints momentary loudness every 0.1 s: average it per second
per_sec = {}
for t, m in re.findall(r"t:\s*([\d.]+)\s+TARGET.*?M:\s*(-?[\d.]+|-inf)", err):
    if m != "-inf":
        per_sec.setdefault(int(float(t)), []).append(float(m))
loud = [round(statistics.mean(per_sec[s]), 1) if s in per_sec else None for s in range(int(dur) + 1)]
lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)

# ---------- 3. transcript, word timings → phrases
words = []
if os.path.exists(MODEL) and shutil.which("whisper-cli"):
    with tempfile.TemporaryDirectory() as tmp:
        run("ffmpeg", "-v", "error", "-i", video, "-ac", "1", "-ar", "16000", "-y", f"{tmp}/a.wav")
        run("whisper-cli", "-m", MODEL, "-f", f"{tmp}/a.wav", "-l", os.environ.get("WLANG", "auto"),
            "-ml", "1", "-oj", "-of", f"{tmp}/w", "--no-prints")
        if os.path.exists(f"{tmp}/w.json"):
            for tk in json.load(open(f"{tmp}/w.json"))["transcription"]:
                t = tk["text"]
                if not t.strip():
                    continue
                s, e = tk["offsets"]["from"] / 1000, tk["offsets"]["to"] / 1000
                if t.startswith(" ") or not words:  # a leading space starts a new word in -ml 1 output
                    words.append({"w": t.strip(), "s": s, "e": e})
                else:
                    words[-1]["w"] += t.strip()
                    words[-1]["e"] = e
words = [w for w in words if w["w"].strip(".,!?…:;-–—")]
phrases = []
for w in words:
    if phrases and w["s"] - phrases[-1]["e"] < 0.5 and not re.search(r"[.!?…]$", phrases[-1]["text"]):
        phrases[-1]["text"] += " " + w["w"]
        phrases[-1]["e"] = w["e"]
    else:
        phrases.append({"s": w["s"], "e": w["e"], "text": w["w"]})

# ---------- 4. sheets
from PIL import Image, ImageDraw, ImageFont

with tempfile.TemporaryDirectory() as fr:
    run("ffmpeg", "-v", "error", "-i", video, "-vf", f"fps={FPS},scale=270:-2", "-q:v", "3", f"{fr}/%05d.jpg")
    frames = sorted(glob.glob(f"{fr}/*.jpg"))
    at = lambda t: frames[min(len(frames) - 1, max(0, int(t * FPS)))]
    font = ImageFont.load_default(size=22)

    def sheet(items, path, cols=6):
        """items = [(time, frame path, extra label)] → one labelled grid"""
        if not items:
            return
        w, h = Image.open(items[0][1]).size
        cols = min(cols, len(items))
        rows = -(-len(items) // cols)
        img = Image.new("RGB", (cols * w, rows * (h + 30)), "white")
        d = ImageDraw.Draw(img)
        for i, (t, p, extra) in enumerate(items):
            x, y = (i % cols) * w, (i // cols) * (h + 30)
            img.paste(Image.open(p), (x, y + 30))
            d.text((x + 6, y + 3), f"{tc(t)} {extra}".strip(), fill="black", font=font)
        img.save(path, quality=85)

    for old in glob.glob(f"{OUT}/*.jpg"):
        os.remove(old)
    sheet([(i / FPS, frames[i], "") for i in range(min(len(frames), 3 * FPS))], f"{OUT}/hook.jpg")
    shot_items = [(a, at(a + 0.1), f"#{k + 1} {b - a:.1f}s") for k, (a, b) in enumerate(shots)]
    overview = [(float(s), at(s), "") for s in range(int(dur) + 1)]
    for name, items in (("shots", shot_items), ("overview", overview)):
        for n in range(0, len(items), 24):
            sheet(items[n:n + 24], f"{OUT}/{name}-{n // 24 + 1}.jpg")

# ---------- 5. report
data = {"meta": meta, "duration": round(dur, 2), "size": size, "cuts": [round(c, 2) for c in cuts],
        "shots": [[round(a, 2), round(b, 2)] for a, b in shots], "lufs": float(lufs[-1]) if lufs else None,
        "loudness_per_sec": loud, "phrases": phrases, "words": len(words)}
json.dump(data, open(f"{OUT}/analysis.json", "w"), ensure_ascii=False, indent=1)

L = [f"# {slug}", "", f"- источник: {meta.get('webpage_url', src)}"]
if meta.get("uploader"):
    L.append(f"- автор: {meta['uploader']}  · просмотры {meta.get('view_count', '?')} · лайки {meta.get('like_count', '?')}")
L += [f"- {size}, {dur:.1f} с, громкость {data['lufs']} LUFS",
      f"- планов: {len(shots)}, медиана {statistics.median(lens):.2f} с, самый длинный {max(lens):.1f} с, "
      f"склеек в первые 3 с: {sum(c < 3 for c in cuts)}",
      f"- слов: {len(words)}, {len(words) / dur:.1f} слов/с" if words else "- речи не найдено (или нет whisper-cli)"]
if meta.get("description"):
    L += ["", "## Подпись автора", meta["description"][:600]]
L += ["", "## Речь по фразам"] + [f"- {tc(p['s'])}–{tc(p['e'])}  {p['text']}" for p in phrases]
L += ["", "## Склейки", ", ".join(tc(c) for c in cuts) or "нет"]
jumps = [f"{tc(s)}: {a} → {b}" for s, (a, b) in enumerate(zip(loud, loud[1:]), 1)
         if a is not None and b is not None and abs(b - a) >= 6]
L += ["", "## Громкость по секундам (LUFS, momentary)", " ".join(str(v) if v is not None else "—" for v in loud),
      "Перепады ≥ 6 LU: " + (", ".join(jumps) or "нет")]
L += ["", "## Листы кадров", "hook.jpg — первые 3 с по 0,25 с; shots-N.jpg — начало каждого плана; overview-N.jpg — каждая секунда"]
open(f"{OUT}/analysis.md", "w").write("\n".join(L) + "\n")

print(f"→ {OUT}")
print(f"  {dur:.1f}s {size}  shots {len(shots)}  median {statistics.median(lens):.2f}s  words {len(words)}")
print("  " + " ".join(sorted(os.path.basename(p) for p in glob.glob(f"{OUT}/*.jpg"))))
