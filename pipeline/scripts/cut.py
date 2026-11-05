#!/usr/bin/env python3
"""Turn a raw take into public/footage.mp4 + a captions.json skeleton.

    python3 scripts/cut.py ../takes/1.MOV [squeeze_over] [keep_pause]

Run from the Remotion project (the folder with package.json; this script lives in its scripts/).
`squeeze_over` / `keep_pause` are in seconds and default to reels.config.json → cut (0.65 / 0.30
if there is no config). Lower them when a take
is delivered tight: the splices are also what the punch-ins hang off (see below), so a two-minute
take with one pause long enough to cut has no rhythm to work with. Aim for 10-15 splices over two
minutes; 0.45 / 0.24 is about the floor. A pause has to be longer than `keep_pause + 2*PAD`
before anything is actually removed.

Language and transcription engine come from reels.config.json (`language`, `transcription`:
"whisper" = local whisper.cpp, "elevenlabs" = ElevenLabs Scribe, key in .env).
Env overrides: WLANG=en, QUIET=-46 (noisy room), SPEED=1.1 (faster delivery),
DROP="12.40-15.80,48.10-50.30" (remove retakes, source seconds), SIZE=1296x2304 (downscale cap),
KEEPS=../edits/9/keeps.json (re-cut exactly as archived — no pause detection, same splices).

What it does, and why each step is the way it is:

1. Squeeze the pauses. silencedetect at -34dB decides WHICH pauses exist (it correctly counts
   a breath as one). It does NOT decide where they start: a soft final consonant sits under
   -34dB, so it opens the pause up to 0.45s early and the cut eats the end of the word.
   Lowering the detector threshold is not the fix — at -45dB it misses whole pauses, because
   the room tone is louder than the tail. So each boundary is refined against a 20ms RMS
   envelope at -55dB, and PAD seconds of air are kept either side.
2. Encode at the SOURCE resolution, crf 14 (CRF=). A 4K take stays 4K: the punch-ins then crop
   real pixels instead of blowing up a downscaled frame (4K → 1080 → zoom was the main cause of
   soft footage). Nothing is ever upscaled: a 1080p take stays 1080p. SIZE=WxH only caps the size
   (downscale, never up). crf 22 left the footage visibly soft and blocky after Instagram's
   re-encode.
   SPEED != 1 retimes with frame BLENDING (framerate=), not `fps=30`: dropping frames at x1.06
   gives a visible micro-stutter about twice a second.
3. Transcribe the CUT, not the source — word timings then need no remapping, and remapping is
   where they go wrong.

It prints the numbers the composition needs: total frames, and the frame of every splice
(those go straight into the BEATS table in ui/Footage.tsx — a crop change on each splice is
what turns a jump cut into a punch-in).

`em` in the emitted captions is a placeholder: 0 for function words, 1 for the rest. The em:2
payload words (~10%) and the ~7 `accent` words are assigned BY MEANING afterwards.
"""
import json, math, os, re, struct, subprocess, sys, wave

WIN = 0.02            # RMS analysis window
QUIET = float(os.environ.get("QUIET", "-55"))  # below this is true silence, not a consonant tail
# or a breath. A noisier room (room tone around -50 dB) needs QUIET=-46, or no pause is cut.
MIN_PAUSE = 0.30
SQUEEZE_OVER = 0.65   # pauses longer than this get cut...
KEEP_PAUSE = 0.30     # ...down to this
PAD = 0.08            # air kept either side of a cut (anti-patterns: tail + ~0.08s)
# Default: the source resolution as is. SIZE=WxH is a cap — it only ever shrinks.
SIZE = os.environ.get("SIZE", "")
MODEL = os.path.expanduser(os.environ.get("WHISPER_MODEL", "~/.cache/whisper/ggml-large-v3-turbo.bin"))
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the Remotion project
_cfg = os.path.join(here, "reels.config.json")
CONFIG = json.load(open(_cfg)) if os.path.exists(_cfg) else {}
LANG = os.environ.get("WLANG", CONFIG.get("language") or "auto")
ENGINE = os.environ.get("TRANSCRIBE", CONFIG.get("transcription", "whisper"))
# SPEED=1.15 plays the whole cut faster (a fast talker reads as energetic). Applied HERE,
# not in the master, so the transcript, the splice frames and the composition all live on the
# sped timeline and the graphics still animate at their own pace.
SPEED = float(os.environ.get("SPEED", CONFIG.get("cut", {}).get("speed", 1)))
# DROP="12.40-15.80,48.10-50.30" removes retakes / false starts (SOURCE seconds, bounds inside
# pauses — find them by chunk transcription + an RMS envelope) in the same single encode.
DROP = [tuple(map(float, r.split("-"))) for r in os.environ.get("DROP", "").split(",") if r]
# OUT=../edits/12 writes footage.mp4 / captions.json / keeps.json there instead of public/, so a
# second video can be cut without touching the edit in progress.
OUT = os.path.abspath(os.environ.get("OUT", os.path.join(here, "public")))
# KEEPS=path/keeps.json: reproduce an archived cut exactly (same source ranges, speed, size, crf).
# Videos 1-8 of the first project could not be re-rendered because the splices were never saved.
KEEPS = json.load(open(os.environ["KEEPS"])) if os.environ.get("KEEPS") else None
CRF = os.environ.get("CRF", "14")
if KEEPS:
    SPEED, SIZE, CRF = KEEPS["speed"], KEEPS.get("size", ""), str(KEEPS.get("crf", CRF))

FILLER = {
    "о", "том", "как", "в", "и", "с", "по", "это", "я", "ну", "вот", "а", "что",
    "но", "до", "на", "от", "его", "им", "тому", "уже", "если", "еще", "чем",
    "их", "мы", "к", "у", "же", "ли", "то", "за", "они", "есть", "будет", "буду",
    "будем", "не", "или", "более", "был", "была", "было", "были", "так", "там",
    "a", "an", "the", "to", "of", "in", "and", "or", "but", "is", "are", "it", "that",
    "this", "you", "your", "i", "we", "if", "for", "with", "at", "on", "do", "be",
}

src = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else (KEEPS or {}).get("src", ""))
if not os.path.exists(src):
    sys.exit(f"take not found: {src or '(none given)'}")
SQUEEZE_OVER = CONFIG.get("cut", {}).get("squeeze_over", SQUEEZE_OVER)
KEEP_PAUSE = CONFIG.get("cut", {}).get("keep_pause", KEEP_PAUSE)
if len(sys.argv) > 2:
    SQUEEZE_OVER = float(sys.argv[2])
if len(sys.argv) > 3:
    KEEP_PAUSE = float(sys.argv[3])
tmp = os.path.join(here, "out", "cut-tmp")
os.makedirs(tmp, exist_ok=True)


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def envelope(wav):
    w = wave.open(wav, "rb")
    n = w.getnframes()
    pcm = struct.unpack(f"<{n}h", w.readframes(n))
    step = int(w.getframerate() * WIN)
    out = []
    for i in range(0, n - step, step):
        acc = 0
        for v in pcm[i : i + step]:
            acc += v * v
        rms = math.sqrt(acc / step) / 32768
        out.append(20 * math.log10(rms) if rms > 1e-9 else -120.0)
    return out


def env_key(name):
    """A key from video/.env without ever printing it."""
    for line in open(os.path.join(here, ".env")):
        k, _, v = line.strip().partition("=")
        if k == name and v:
            return v.strip().strip('"')
    sys.exit(f"{name} is not set in video/.env")


def words_from_elevenlabs(wav):
    """ElevenLabs Scribe: word-level timestamps, no local model needed."""
    out = f"{tmp}/scribe.json"
    r = run("curl", "-sS", "-o", out, "-w", "%{http_code}",
            "https://api.elevenlabs.io/v1/speech-to-text",
            "-H", f"xi-api-key: {env_key('ELEVENLABS_API_KEY')}",
            "-F", "model_id=scribe_v2", *(["-F", f"language_code={LANG}"] if LANG != "auto" else []),
            "-F", "timestamps_granularity=word", "-F", f"file=@{wav}")
    if r.stdout.strip() != "200":
        sys.exit(f"Scribe failed ({r.stdout.strip()}): {open(out).read()[:300]}")
    return [{"w": t["text"].strip(), "s": t["start"], "e": t["end"]}
            for t in json.load(open(out))["words"]
            if t.get("type") == "word" and t["text"].strip(".,!?…:;-–—").strip()]


def words_from(wav, tag):
    if ENGINE == "elevenlabs":
        return words_from_elevenlabs(wav)
    run("whisper-cli", "-m", MODEL, "-f", wav, "-l", LANG, "-ml", "1", "-oj",
        "-of", f"{tmp}/{tag}", "--no-prints")
    toks = json.load(open(f"{tmp}/{tag}.json"))["transcription"]
    out = []
    for tk in toks:
        t = tk["text"]
        if not t.strip():
            continue
        s, e = tk["offsets"]["from"] / 1000, tk["offsets"]["to"] / 1000
        # a leading space is what marks the start of a new word in -ml 1 output
        if t.startswith(" ") or not out:
            out.append({"w": t.strip(), "s": s, "e": e})
        else:
            out[-1]["w"] += t.strip()
            out[-1]["e"] = e
    return [w for w in out if w["w"].strip(".,!?…:;-–—")]


# ---------- 1. pauses
run("ffmpeg", "-v", "error", "-i", src, "-ac", "1", "-ar", "16000", "-y", f"{tmp}/src.wav")
env = envelope(f"{tmp}/src.wav")

quiet = lambda t: 0 <= int(t / WIN) < len(env) and env[int(t / WIN)] < QUIET

def true_start(a, b):
    while a < b and not quiet(a):
        a += WIN
    return a

def true_end(a, b):
    while b > a and not quiet(b - WIN):
        b -= WIN
    return b

err = run("ffmpeg", "-hide_banner", "-nostats", "-i", f"{tmp}/src.wav",
          "-af", f"silencedetect=n=-34dB:d={MIN_PAUSE}", "-f", "null", "-").stderr
gaps, st = [], None
for L in err.splitlines():
    m = re.search(r"silence_start: ([\d.]+)", L)
    if m:
        st = float(m.group(1))
    m = re.search(r"silence_end: ([\d.]+)", L)
    if m and st is not None:
        gaps.append((st, float(m.group(1))))
        st = None
SRC_DUR = len(env) * WIN
if st is not None:  # a silence still open at EOF
    gaps.append((st, SRC_DUR))

# Leading / trailing silence is trimmed only if it really touches the start / the end: a take
# that stops mid-word has no trailing silence, and its last PAUSE must not be taken for one —
# that silently cut the whole last phrase.
HEAD = max(0.0, true_end(0.0, gaps[0][1]) - 0.25) if gaps and gaps[0][0] < 0.05 else 0.0
TAIL = (true_start(gaps[-1][0], gaps[-1][1]) + 0.25
        if gaps and gaps[-1][1] > SRC_DUR - 0.05 else SRC_DUR)
drops, rescued = [(0.0, HEAD), (TAIL, 1e9)], 0
for a, b in gaps:
    if a < HEAD or b > TAIL:
        continue
    ta, tb = true_start(a, b), true_end(a, b)
    if ta - a > 0.1:
        rescued += 1
    if tb - ta > SQUEEZE_OVER:
        lo, hi = ta + PAD + KEEP_PAUSE / 2, tb - PAD - KEEP_PAUSE / 2
        if hi - lo > 0.05:
            drops.append((lo, hi))
drops += DROP
drops.sort()

keeps, t = [], 0.0
for a, b in drops:
    if a > t:
        keeps.append((t, a))
    t = max(t, b)
keeps = [(a, b) for a, b in keeps if b - a > 0.01]
if KEEPS:
    keeps = [tuple(k) for k in KEEPS["keeps"]]

acc, cuts = 0.0, []
for a, b in keeps[:-1]:
    acc += b - a
    cuts.append(acc / SPEED)
DUR = (acc + (keeps[-1][1] - keeps[-1][0])) / SPEED

# ---------- 2. encode
fc = "".join(
    f"[0:v]trim={a}:{b},setpts=PTS-STARTPTS[v{i}];"
    f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{i}];" for i, (a, b) in enumerate(keeps))
fc += "".join(f"[v{i}][a{i}]" for i in range(len(keeps)))
# speed 1: fps=30 only normalises a VFR phone take. Any other speed: blend, never drop frames.
retime = "fps=30" if SPEED == 1 else f"setpts=PTS/{SPEED},framerate=fps=30"
# SIZE caps, never enlarges: min() keeps a smaller source at its own size
if SIZE:
    W, H = SIZE.lower().split("x")
    retime += (f",scale=w='min(iw,{W})':h='min(ih,{H})':force_original_aspect_ratio=decrease"
               f":force_divisible_by=2:flags=lanczos")
# Phone takes come both limited and full range (yuvj420p, pc): convert to BT.709 limited range and
# tag all four colour fields, so nothing downstream guesses (an untagged file is read differently
# by Remotion, ffmpeg and every platform).
retime += (",scale=out_color_matrix=bt709:out_range=limited,format=yuv420p,"
           "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv")
fc += f"concat=n={len(keeps)}:v=1:a=1[cv][ca];[cv]{retime}[v];[ca]atempo={SPEED},aresample=48000,aformat=channel_layouts=stereo[a]"
open(f"{tmp}/filter.txt", "w").write(fc)

os.makedirs(OUT, exist_ok=True)
# The full recipe of this cut: KEEPS=<this file> python3 scripts/cut.py reproduces footage.mp4
# frame for frame, so the splice table and the cutouts stay valid for a re-render.
json.dump({"src": src, "speed": SPEED, "size": SIZE, "crf": int(CRF),
           "squeeze_over": SQUEEZE_OVER, "keep_pause": KEEP_PAUSE, "quiet": QUIET,
           "drop": [list(d) for d in DROP],
           "keeps": [[round(a, 3), round(b, 3)] for a, b in keeps]},
          open(os.path.join(OUT, "keeps.json"), "w"), indent=1)
dst = os.path.join(OUT, "footage.mp4")
r = subprocess.run(
    ["ffmpeg", "-hide_banner", "-v", "warning", "-i", src, "-/filter_complex", f"{tmp}/filter.txt",
     "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", CRF,
     "-preset", "medium", "-g", "30", "-pix_fmt", "yuv420p",
     "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
     "-c:a", "aac", "-ar", "48000", "-b:a", "320k", "-movflags", "+faststart", "-y", dst])
if r.returncode:
    sys.exit("encode failed")

frames = int(subprocess.run(
    ["ffprobe", "-v", "error", "-select_streams", "v", "-count_frames",
     "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", dst],
    capture_output=True, text=True).stdout.strip().rstrip(","))

# ---------- 3. verify no splice landed on speech, then transcribe the cut
run("ffmpeg", "-v", "error", "-i", dst, "-ac", "1", "-ar", "16000", "-y", f"{tmp}/cut.wav")
cenv = envelope(f"{tmp}/cut.wav")
cdb = lambda t: cenv[int(t / WIN)] if 0 <= int(t / WIN) < len(cenv) else -120
bad = [c for c in cuts if cdb(c - 0.06) > -45 or cdb(c + 0.04) > -45]

words = words_from(f"{tmp}/cut.wav", "cut")
caps = []
for w in words:
    key = w["w"].strip(".,!?…:;»«\"").lower()
    caps.append({"w": w["w"], "s": round(w["s"], 2), "e": round(w["e"], 2),
                 "em": 0 if key in FILLER else 1})
json.dump(caps, open(os.path.join(OUT, "captions.json"), "w"),
          ensure_ascii=False, indent=0)

res = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                      "stream=width,height", "-of", "csv=p=0:s=x", dst],
                     capture_output=True, text=True).stdout.strip()
print(f"\nfootage.mp4  {res}  {DUR:.2f}s  {frames} frames   ({rescued} pauses whose -34dB start was "
      f"inside a word tail)")
print(f"DURATION = {frames}")
print("Footage.tsx splice frames:", [round(c * 30) for c in cuts])
print(f"captions.json: {len(caps)} words — assign em:2 and accent by MEANING before rendering")
if bad:
    print(f"!! {len(bad)} splices land on speech: {[round(c, 2) for c in bad]}")
else:
    print("all splices sit in silence")
if not cuts:
    print("!! no splices: the pauses are shorter than squeeze_over, or the room is louder than "
          "QUIET — lower the args (floor ~0.45 0.24) or re-run with QUIET=-46")
