#!/usr/bin/env python3
"""The user's own sound-effect library: folders by purpose, every file named for when to use it.

    python3 scripts/sfx.py where                         # where the library is (or that there is none)
    python3 scripts/sfx.py init [PATH]                   # create it (default ~/reels-sfx) and remember the path
    python3 scripts/sfx.py scan URL|FILE|SLUG ...        # find sound moments in reels -> candidates
    python3 scripts/sfx.py sep-setup                     # install Demucs (voice separation), once, ~2 GB
    python3 scripts/sfx.py cut CUTS.tsv                  # cut the chosen moments into the library
    python3 scripts/sfx.py add FILE FOLDER NAME "когда ставить" [--src TEXT] [--guess]
    python3 scripts/sfx.py check [NAME ...]              # whisper over clips: did any voice slip in?
    python3 scripts/sfx.py index                         # rebuild INDEX.md from index.json
    python3 scripts/sfx.py use NAME ... --to video/public/sfx   # copy sounds into an editing project

The path is kept in ~/.config/reelsology/config.json -> "sfx_library" (env SFX_LIBRARY wins).
Library layout: <folder>/<name>.wav + index.json (truth) + INDEX.md (generated, for people).
Every file: WAV 48 kHz, peak -1 dBFS, silence before the attack trimmed, so the file start goes on
the event frame.

CUTS.tsv, one sound per line, tab-separated:
    source  start  end  folder  name  когда ставить  [guess]
source = a work/ slug (or part of it), or a path to a video/audio file; start/end in seconds;
         SLUG#nv = the reel with the voice removed by Demucs, SLUG#other = also without drums/bass
         (for reels with a music bed); scan writes the right source for every candidate;
guess = 1 when the name was inferred (order of cards, waveform shape), not read off the frame.
"""
import glob, json, os, re, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
CFG = os.path.expanduser("~/.config/reelsology/config.json")
MODEL = os.path.expanduser(os.environ.get("WHISPER_MODEL", "~/.cache/whisper/ggml-large-v3-turbo.bin"))
SR = 44100
SEP_ENV = os.path.expanduser(os.environ.get("SFX_SEP_ENV", "~/.local/share/reelsology/demucs-venv"))
DEMUCS = os.path.join(SEP_ENV, "bin", "demucs")

FOLDERS = {
    "01-perehody": "Переходы: склейки, зум, свайп, перемотка",
    "02-napryazhenie": "Напряжение и драма: жуть, интрига, тревога, плохая новость",
    "03-akcenty": "Акценты: удар на слово, цифру, заголовок",
    "04-memnye": "Мемные и комедия: реакции, неловкость, провал",
    "05-pravilno-nepravilno": "Правильно / неправильно",
    "06-interfeys": "Интерфейс: клики, клавиатура, телефон, загрузка",
    "07-dengi": "Деньги",
    "08-cenzura": "Цензура (бип)",
    "09-multyashnye": "Мультяшные и ретро: стикеры, поп, пружинка",
    "10-ekshn-foley": "Экшн и бытовые (foley): звук действия в кадре",
    "11-igrovye": "Игровые: монетка, уровень, уведомление",
}
# whisper "hears" these in silence or pure SFX; they are not a voice
HALLU = re.compile(r"^(you|thank you|thanks|bye|mmm+|ok|\.|all|продолжение следует|редактор субтитров.*|субтитры.*|"
                   r"ご視聴ありがとうございました|we'?ll be right back)$", re.I)


def run(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def die(msg):
    print(msg)
    sys.exit(1)


# ---------- library location and index ----------

def lib_path(required=True):
    p = os.environ.get("SFX_LIBRARY")
    if not p and os.path.exists(CFG):
        p = json.load(open(CFG)).get("sfx_library")
    if p:
        p = os.path.expanduser(p)
    if required and (not p or not os.path.isdir(p)):
        die("Библиотеки звуков нет. Создать: python3 scripts/sfx.py init [~/reels-sfx]")
    return p


def load_index(L):
    f = os.path.join(L, "index.json")
    d = json.load(open(f)) if os.path.exists(f) else {}
    if isinstance(d, list):  # old flat format
        d = {"sounds": d}
    d.setdefault("folders", dict(FOLDERS))
    d.setdefault("sounds", [])
    return d


def save_index(L, d):
    json.dump(d, open(os.path.join(L, "index.json"), "w"), ensure_ascii=False, indent=1)
    write_md(L, d)


def write_md(L, d):
    known = {s["file"] for s in d["sounds"]}
    out = ["# Библиотека звуков для рилсов", "",
           "Папка по задаче, файл по названию. Колонка «Когда ставить» — для чего звук. WAV 48 кГц, пик −1 дБ, "
           "тишина до атаки срезана: начало файла ставить на кадр события (или на кадр раньше).", "",
           "Громкость в монтаже: под речью 10–15 %, на паузе или событии громче, речь под акцентом приглушить "
           "на 6–10 дБ; райзер под хук около 15 %.", "",
           "«≈» — название угадано (по порядку карточек или форме волны), а не прочитано с кадра: проверь на слух.",
           "Звуки, вырезанные из рилсов, звучат не как студийные: Instagram сжимает звук, местами под эффектом "
           "есть подложка. Для важного ролика найди оригинал по названию (CapCut, Mixkit, Freesound CC0).", ""]
    folders = dict(d["folders"])
    for s in d["sounds"]:
        folders.setdefault(s["file"].split("/")[0], "")
    for folder in sorted(folders):
        rs = sorted([s for s in d["sounds"] if s["file"].startswith(folder + "/")], key=lambda s: s["file"])
        if not rs:
            continue
        out += [f"## {folder} — {folders[folder]}".rstrip(" —"), "",
                "| Файл | Когда ставить | Длина | Откуда |", "|---|---|---|---|"]
        for s in rs:
            mark = " ≈" if s.get("guess") else ""
            out.append(f"| `{os.path.basename(s['file'])}`{mark} | {s['desc']} | {s['dur']} с | {s.get('src', '')} |")
        out.append("")
    stray = [os.path.relpath(f, L) for f in glob.glob(os.path.join(L, "*", "*.*"))
             if f.lower().endswith((".wav", ".mp3", ".m4a", ".aiff")) and os.path.relpath(f, L) not in known]
    if stray:
        out += ["## Без описания", "", "Лежат в папках, но не описаны: `sfx.py add` с описанием или удалить.", ""]
        out += [f"- `{f}`" for f in sorted(stray)] + [""]
    open(os.path.join(L, "INDEX.md"), "w").write("\n".join(out))


def uniq(L, folder, name):
    name = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "zvuk"
    base, k = name, 2
    while os.path.exists(os.path.join(L, folder, name + ".wav")):
        name = f"{base}-{k}"
        k += 1
    return name


# ---------- audio ----------

def pcm(path, start=None, end=None):
    import numpy as np
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", str(start), "-to", str(end)]
    cmd += ["-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, dtype=np.int16).astype(float) / 32768


def env_db(x, hop_s=0.01):
    import numpy as np
    hop = int(hop_s * SR)
    return np.array([20 * np.log10(np.sqrt(np.mean(x[k:k + hop] ** 2)) + 1e-9) for k in range(0, len(x) - hop, hop)])


def render(src, start, end, dst, trim=True):
    """Cut, trim silence before the attack, fade, peak-normalise to -1 dBFS, write WAV 48k."""
    if trim:
        db = env_db(pcm(src, start, end))
        if len(db) and db.max() > -60:
            on = next(i for i, v in enumerate(db) if v > db.max() - 30)
            start = start + max(0, on * 0.01 - 0.01)
    d = end - start
    fo = min(0.06, d / 4)
    tmp = dst + ".tmp.wav"
    r = run("ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", src, "-vn",
            "-af", f"afade=t=in:d=0.005,afade=t=out:st={d - fo:.3f}:d={fo:.3f}", "-ar", "48000", "-c:a", "pcm_s16le", tmp)
    if r.returncode:
        die(r.stderr)
    mx = float(re.search(r"max_volume: (-?[\d.]+)", run("ffmpeg", "-i", tmp, "-af", "volumedetect", "-f", "null", "-").stderr).group(1))
    run("ffmpeg", "-v", "error", "-y", "-i", tmp, "-af", f"volume={-1 - mx:.2f}dB", "-ar", "48000", "-c:a", "pcm_s16le", dst)
    os.remove(tmp)
    return round(d, 2)


def duration(path):
    return float(run("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path).stdout.strip() or 0)


def whisper_words(path, tmpdir):
    """Word-level timestamps: [(start, end, word)]. Bracketed tags like *BOOM* / [Music] are dropped."""
    w16 = os.path.join(tmpdir, "w16.wav")
    run("ffmpeg", "-v", "error", "-y", "-i", path, "-vn", "-ar", "16000", "-ac", "1", w16)
    base = os.path.join(tmpdir, "words")
    run("whisper-cli", "-m", MODEL, "-l", "auto", "-ml", "1", "-sow", "-oj", "-of", base, "-np", w16)
    d = json.load(open(base + ".json"))
    out = []
    for s in d["transcription"]:
        t = s["text"].strip()
        if re.search(r"\w", t) and not re.match(r"^[\[\(\*]", t):
            out.append((s["offsets"]["from"] / 1000, s["offsets"]["to"] / 1000, t))
    return out


def voice_text(path, tmpdir):
    w = os.path.join(tmpdir, "chk.wav")
    run("ffmpeg", "-v", "error", "-y", "-i", path, "-ar", "16000", "-ac", "1", "-af", "apad=pad_dur=1", w)
    t = " ".join(run("whisper-cli", "-m", MODEL, "-l", "auto", "-nt", "-np", w).stdout.split())
    t = re.sub(r"[\*\[\(][^\*\]\)]*[\*\]\)]", "", t).strip()
    words = [x for x in re.split(r"[\s,!?]+", t) if x]
    suspicious = bool(t) and not HALLU.match(t.strip(" .")) and len(words) >= 2
    return t, suspicious


# ---------- voice separation (Demucs) ----------

def sep_ready():
    return os.path.exists(DEMUCS)


def separate(video, wdir, four=False):
    """Stems cached in <wdir>/sfx/sep/: nv.wav (all but voice), vocals.wav; four=True adds other.wav
    (no voice, drums, bass: what is left of SFX over a music bed). Returns the folder."""
    sd = os.path.join(wdir, "sfx", "sep")
    need = ["nv.wav", "vocals.wav"] + (["other.wav"] if four else [])
    if all(os.path.exists(os.path.join(sd, f)) for f in need):
        return sd
    if not sep_ready():
        die("Demucs не установлен: python3 scripts/sfx.py sep-setup")
    os.makedirs(sd, exist_ok=True)
    wav = os.path.join(sd, "in.wav")
    run("ffmpeg", "-v", "error", "-y", "-i", video, "-vn", "-ac", "2", "-ar", "44100", wav)
    dev = "mps" if sys.platform == "darwin" else "cpu"
    args = [DEMUCS, "-n", "htdemucs", "-d", dev, "-o", sd] + ([] if four else ["--two-stems", "vocals"]) + [wav]
    r = run(*args)
    if r.returncode and dev == "mps":
        r = run(*[x if x != "mps" else "cpu" for x in args])
    if r.returncode:
        die("Demucs упал:\n" + r.stderr[-800:])
    res = os.path.join(sd, "htdemucs", "in")
    if four:
        shutil.move(os.path.join(res, "other.wav"), os.path.join(sd, "other.wav"))
        if not os.path.exists(os.path.join(sd, "nv.wav")):
            # nv = everything but the voice
            parts = [os.path.join(res, f + ".wav") for f in ("drums", "bass")] + [os.path.join(sd, "other.wav")]
            run("ffmpeg", "-v", "error", "-y", *sum((["-i", x] for x in parts), []), "-filter_complex",
                f"amix=inputs=3:normalize=0", os.path.join(sd, "nv.wav"))
    else:
        shutil.move(os.path.join(res, "no_vocals.wav"), os.path.join(sd, "nv.wav"))
    if not os.path.exists(os.path.join(sd, "vocals.wav")):
        shutil.move(os.path.join(res, "vocals.wav"), os.path.join(sd, "vocals.wav"))
    shutil.rmtree(os.path.join(sd, "htdemucs"), ignore_errors=True)
    os.remove(wav)
    return sd


def cmd_sep_setup(a):
    if sep_ready():
        print(f"Demucs уже стоит: {DEMUCS}")
        return
    py = shutil.which("python3.11") or os.path.expanduser("~/.local/bin/python3.11")
    if not os.path.exists(py):
        py = shutil.which("python3.12") or shutil.which("python3.10") or sys.executable
    print(f"ставлю Demucs в {SEP_ENV} (≈2 ГБ, один раз)…")
    for cmd in ([py, "-m", "venv", SEP_ENV], [os.path.join(SEP_ENV, "bin", "pip"), "install", "-q", "--upgrade", "pip"],
                [os.path.join(SEP_ENV, "bin", "pip"), "install", "-q", "demucs", "soundfile"]):
        r = run(*cmd)
        if r.returncode:
            die(r.stderr[-800:])
    print("готово" if sep_ready() else "не получилось")


def detect(db, A, B, floor=None):
    """Events in db[A:B] (10 ms bins): [(s, e, peak, floor)] in bins, absolute."""
    import numpy as np
    seg = db[A:B]
    if not len(seg) or seg.max() < -35:
        return []
    fl = float(np.percentile(seg, 10)) if floor is None else floor
    act = seg > max(-42, fl + 8)
    runs, k = [], 0
    while k < len(act):
        if act[k]:
            j = k
            while j < len(act) and act[j]:
                j += 1
            runs.append([k, j])
            k = j
        else:
            k += 1
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < 8:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(A + s, A + e, float(seg[s:e].max()), fl) for s, e in merged if e - s >= 6]


# ---------- commands ----------

def cmd_where(a):
    p = lib_path(required=False)
    if p and os.path.isdir(p):
        d = load_index(p)
        print(f"{p}  ({len(d['sounds'])} звуков, {len({s['file'].split('/')[0] for s in d['sounds']})} папок)")
    else:
        print("нет библиотеки" + (f" (в конфиге {p}, но папки нет)" if p else ""))


def cmd_init(a):
    p = os.path.abspath(os.path.expanduser(a[0] if a else "~/reels-sfx"))
    os.makedirs(p, exist_ok=True)
    d = load_index(p)
    for f in d["folders"]:
        os.makedirs(os.path.join(p, f), exist_ok=True)
    save_index(p, d)
    if os.environ.get("SFX_LIBRARY"):
        print(f"библиотека: {p} (SFX_LIBRARY, конфиг не тронут)")
        return
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    cfg = json.load(open(CFG)) if os.path.exists(CFG) else {}
    cfg["sfx_library"] = p.replace(os.path.expanduser("~"), "~", 1)
    json.dump(cfg, open(CFG, "w"), ensure_ascii=False, indent=1)
    print(f"библиотека: {p}\nпапки: {', '.join(d['folders'])}")


def resolve_video(src):
    """-> (path to cut from, work dir). SLUG#nv / SLUG#other -> the Demucs stem of that reel."""
    if "#" in src and not os.path.exists(src):
        base, layer = src.rsplit("#", 1)
        video, wdir = resolve_video(base)
        sd = separate(video, wdir, four=(layer == "other"))
        return os.path.join(sd, layer + ".wav"), wdir
    if os.path.exists(src):
        return src, None
    hits = [h for h in glob.glob(os.path.join(WORK, f"*{src}*")) if os.path.isdir(h)]
    if hits:
        return os.path.join(sorted(hits)[-1], "video.mp4"), sorted(hits)[-1]
    m = re.search(r"/(?:p|reels?|shorts|video)/([\w-]+)", src)
    if m:
        hits = glob.glob(os.path.join(WORK, f"*{m.group(1)}*"))
        if hits:
            return os.path.join(sorted(hits)[-1], "video.mp4"), sorted(hits)[-1]
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "intake.py"), src], capture_output=True, text=True)
    m = re.search(r"→ (\S.*)", r.stdout)
    if not m:
        die(f"не скачалось: {src}\n{r.stdout[-500:]}{r.stderr[-500:]}")
    d = m.group(1).strip()
    return os.path.join(d, "video.mp4"), d


def cmd_scan(a):
    """Voice-free sound events in each reel -> work/<slug>/sfx/candidates.md + frame sheets."""
    import numpy as np
    flags = [x for x in a if x.startswith("--")]
    a = [x for x in a if not x.startswith("--")]
    if not a:
        die("sfx.py scan URL|FILE|SLUG ... [--no-sep]")
    for src in a:
        video, wdir = resolve_video(src)
        out = os.path.join(wdir or os.path.dirname(os.path.abspath(video)), "sfx")
        os.makedirs(out, exist_ok=True)
        words = whisper_words(video, out)
        x = pcm(video)
        dur = len(x) / SR
        db = env_db(x)
        M = 0.10  # margin around every word
        speech = sorted((max(0, s - M), e + M) for s, e, _ in words)
        gaps, t = [], 0.0
        for s, e in speech:
            if s > t:
                gaps.append((t, s))
            t = max(t, e)
        if dur > t:
            gaps.append((t, dur))
        ev = []
        for g0, g1 in gaps:
            if g1 - g0 < 0.2:
                continue
            for bs, be, pk, fl in detect(db, int(g0 * 100), int(g1 * 100)):
                ev.append(dict(start=round(max(g0, bs / 100 - 0.03), 2), end=round(min(g1, be / 100 + 0.08), 2),
                               peak=round(pk, 1), floor=round(fl, 1), source=os.path.basename(wdir or video) if wdir else video, layer="оригинал"))
        # under the voice: Demucs strips the voice, then the whole timeline is searched
        sep_note = ""
        if words and wdir and "--no-sep" not in flags:
            if sep_ready():
                import numpy as np
                sd = separate(video, wdir)
                # a music bed under everything (floor of the voice-free track above -40 dB) -> drop drums/bass too
                bed = float(np.percentile(env_db(pcm(os.path.join(sd, "nv.wav"))), 10)) > -40
                if bed:
                    separate(video, wdir, four=True)
                layer = "other" if bed else "nv"
                sx = env_db(pcm(os.path.join(sd, layer + ".wav")))
                vx = env_db(pcm(os.path.join(sd, "vocals.wav")))
                slug = os.path.basename(wdir).split("-", 3)[-1]
                for bs, be, pk, fl in detect(sx, 0, len(sx), floor=float(np.percentile(sx, 10))):
                    s0, e0 = max(0, bs / 100 - 0.03), be / 100 + 0.08
                    if any(x["start"] < e0 and x["end"] > s0 for x in ev):
                        continue
                    ev.append(dict(start=round(s0, 2), end=round(e0, 2), peak=round(pk, 1), floor=round(fl, 1),
                                   source=f"{slug}#{layer}", layer="без голоса" + (" и бита" if bed else ""),
                                   voice=round(float(np.percentile(vx[bs:be], 90)), 1) if be <= len(vx) else None))
                ev.sort(key=lambda x: x["start"])
            else:
                sep_note = ("Под голосом звуки не искались: нет Demucs. Поставить (≈2 ГБ, с согласия пользователя): "
                            "python3 scripts/sfx.py sep-setup, потом scan ещё раз.")
        # one frame per event (labels on screen usually name the sound), 12 per sheet, row-major order
        frames = []
        for n, e in enumerate(ev):
            f = os.path.join(out, f"ev{n:02d}.jpg")
            run("ffmpeg", "-v", "error", "-y", "-ss", f"{min(e['start'] + 0.2, (e['start'] + e['end']) / 2):.2f}", "-i", video,
                "-frames:v", "1", "-vf", "scale=240:-2", f)
            frames.append(f)
        sheets = []
        for p in range(0, len(frames), 12):
            part = frames[p:p + 12]
            inp = sum((["-i", f] for f in part), [])
            lay = "|".join(f"{(k % 6) * 240}_{(k // 6) * 427}" for k in range(len(part)))
            sh = os.path.join(out, f"sheet-{p // 12 + 1}.jpg")
            run("ffmpeg", "-v", "error", "-y", *inp, "-filter_complex",
                "".join(f"[{k}:v]" for k in range(len(part))) + f"xstack=inputs={len(part)}:layout={lay}:fill=black", "-q:v", "3", sh)
            sheets.append(sh)
        json.dump(dict(video=video, words=words, events=ev), open(os.path.join(out, "candidates.json"), "w"), ensure_ascii=False)
        L = [f"# Кандидаты в звуки: {os.path.basename(wdir or video)}", "",
             f"Видео: {video}", f"Речь (слов): {len(words)}. Окна без голоса: {len([g for g in gaps if g[1] - g[0] >= 0.2])}.", "",
             "Кадры событий: " + ", ".join(os.path.basename(s) for s in sheets) + " (по 12 на лист, слева направо, сверху вниз).",
             "floor выше −40 дБ — под звуком, скорее всего, музыкальная подложка.", "",
             "Колонка «source» идёт в CUTS.tsv как есть: #nv / #other — дорожка, где Demucs убрал голос (и бит).",
             "Такие звуки чуть грязнее оригинала: после cut whisper проверит, не осталось ли голоса.", "",
             "| # | начало | конец | длина | пик дБ | фон дБ | слой | source |", "|---|---|---|---|---|---|---|---|"]
        L += [f"| {n} | {e['start']:.2f} | {e['end']:.2f} | {e['end'] - e['start']:.2f} | {e['peak']} | {e['floor']} | {e['layer']} | {e['source']} |"
              for n, e in enumerate(ev)]
        if sep_note:
            L += ["", sep_note]
        if not ev:
            L += ["", "Звуков не найдено."]
        open(os.path.join(out, "candidates.md"), "w").write("\n".join(L) + "\n")
        under = sum(1 for e in ev if e["layer"] != "оригинал")
        print(f"{os.path.basename(wdir or video)}: {len(ev)} звуков ({under} из-под голоса) → {out}/candidates.md"
              + (f"\n  {sep_note}" if sep_note else ""))


def add_entry(L, d, folder, name, desc, dur, src, guess):
    d["folders"].setdefault(folder, "")
    d["sounds"].append(dict(file=f"{folder}/{name}.wav", desc=desc, dur=dur, src=src, guess=bool(guess)))


def src_label(wdir, start, end):
    if not wdir:
        return ""
    meta = os.path.join(wdir, "meta.json")
    who = ""
    if os.path.exists(meta):
        m = json.load(open(meta))
        who = (m.get("uploader") or "").split("|")[0].strip()
    rid = os.path.basename(wdir).split("-", 3)[-1]
    return f"{who}, {rid} @ {start:.2f}-{end:.2f}".strip(", ")


def cmd_cut(a):
    if not a:
        die("sfx.py cut CUTS.tsv")
    L = lib_path()
    d = load_index(L)
    tmp = os.path.join(L, ".tmp")
    os.makedirs(tmp, exist_ok=True)
    made, warn = [], []
    for line in open(a[0]):
        if not line.strip() or line.startswith("#"):
            continue
        p = line.rstrip("\n").split("\t")
        src, s, e, folder, name, desc = p[:6]
        guess = len(p) > 6 and p[6].strip() not in ("", "0")
        s, e = float(s), float(e)
        video, wdir = resolve_video(src)
        os.makedirs(os.path.join(L, folder), exist_ok=True)
        name = uniq(L, folder, name)
        dst = os.path.join(L, folder, name + ".wav")
        dur = render(video, s, e, dst)
        text, sus = voice_text(dst, tmp)
        if sus:
            warn.append(f"{folder}/{name}.wav: whisper слышит «{text}»")
        add_entry(L, d, folder, name, desc, dur, src_label(wdir, s, e) + (" (голос убран Demucs)" if "#" in src else ""), guess)
        made.append(f"{folder}/{name}.wav")
    shutil.rmtree(tmp, ignore_errors=True)
    save_index(L, d)
    print(f"добавлено {len(made)} → {L}")
    if warn:
        print("Проверь, нет ли голоса (часто это мем-голос или галлюцинация whisper):\n  " + "\n  ".join(warn))


def cmd_add(a):
    flags = {"--src": "", "--guess": False, "--no-trim": False}
    rest = []
    i = 0
    while i < len(a):
        if a[i] == "--src":
            flags["--src"] = a[i + 1]
            i += 2
        elif a[i] in ("--guess", "--no-trim"):
            flags[a[i]] = True
            i += 1
        else:
            rest.append(a[i])
            i += 1
    if len(rest) < 4:
        die('sfx.py add FILE FOLDER NAME "когда ставить" [--src TEXT] [--guess] [--no-trim]')
    f, folder, name, desc = rest[:4]
    L = lib_path()
    d = load_index(L)
    os.makedirs(os.path.join(L, folder), exist_ok=True)
    name = uniq(L, folder, name)
    dst = os.path.join(L, folder, name + ".wav")
    dur = render(f, 0, duration(f), dst, trim=not flags["--no-trim"])
    add_entry(L, d, folder, name, desc, dur, flags["--src"] or os.path.basename(f), flags["--guess"])
    save_index(L, d)
    print(f"{folder}/{name}.wav  {dur} с")


def cmd_check(a):
    L = lib_path()
    d = load_index(L)
    tmp = os.path.join(L, ".tmp")
    os.makedirs(tmp, exist_ok=True)
    for s in d["sounds"]:
        if a and not any(x in s["file"] for x in a):
            continue
        text, sus = voice_text(os.path.join(L, s["file"]), tmp)
        print(("ГОЛОС? " if sus else "ok     ") + s["file"] + (f"  «{text}»" if sus else ""))
    shutil.rmtree(tmp, ignore_errors=True)


def cmd_index(a):
    L = lib_path()
    d = load_index(L)
    d["sounds"] = [s for s in d["sounds"] if os.path.exists(os.path.join(L, s["file"]))]
    save_index(L, d)
    print(os.path.join(L, "INDEX.md"))


def cmd_use(a):
    if "--to" not in a:
        die("sfx.py use NAME ... --to video/public/sfx")
    k = a.index("--to")
    names, to = a[:k], a[k + 1]
    L = lib_path()
    os.makedirs(to, exist_ok=True)
    for n in names:
        hits = glob.glob(os.path.join(L, "*", n if n.endswith(".wav") else n + ".wav"))
        if not hits:
            print(f"нет: {n}")
            continue
        shutil.copy2(hits[0], to)
        print(f"{os.path.relpath(hits[0], L)} → {to}")


CMDS = dict(**{"sep-setup": cmd_sep_setup}, where=cmd_where, init=cmd_init, scan=cmd_scan, cut=cmd_cut, add=cmd_add, check=cmd_check, index=cmd_index, use=cmd_use)
if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__)
        sys.exit(1)
    CMDS[sys.argv[1]](sys.argv[2:])
