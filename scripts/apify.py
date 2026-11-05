#!/usr/bin/env python3
"""Optional Apify link: real view counts for the base, and the user's own reels for their own reelsology.

    python3 scripts/apify.py stats [ID ...]        views/likes/comments/date for every source (or the given
                                                   reel ids) → written into sources/*.md, then stats.md
    python3 scripts/apify.py own USERNAME [N]      the user's latest N reels (default 12) with their numbers →
                                                   work/own-USERNAME.json + a table to pick from; then each
                                                   chosen reel goes through intake.py like any other
    python3 scripts/apify.py table                 rebuild stats.md from sources/*.md, no network

Instagram gives anonymous yt-dlp likes and comments only; plays come from Apify (apify/instagram-scraper,
pay per result, ~$0.003 a reel). The token is read from APIFY_TOKEN (or ~/.config/reelsology/apify_token)
and never printed. No token: say so and stop — the Apify MCP plugin, if connected, does the same job by hand.
"""
import glob, json, os, re, sys, urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACTOR = "apify~instagram-scraper"
TOKEN_FILE = os.path.expanduser("~/.config/reelsology/apify_token")


def token():
    t = os.environ.get("APIFY_TOKEN") or (open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else "")
    if not t:
        sys.exit("нет APIFY_TOKEN: задай переменную окружения или положи токен в " + TOKEN_FILE +
                 " (или собери данные через плагин Apify)")
    return t


def run_actor(inp):
    req = urllib.request.Request(f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items",
                                 data=json.dumps(inp).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token()}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def row(it):
    return {"id": it.get("shortCode"), "views": it.get("videoPlayCount") or it.get("videoViewCount"),
            "likes": it.get("likesCount"), "comments": it.get("commentsCount"),
            "published": (it.get("timestamp") or "")[:10], "duration": it.get("videoDuration"),
            "owner": it.get("ownerUsername"), "url": it.get("url")}


def sources():
    out = {}
    for f in glob.glob(os.path.join(ROOT, "sources", "*.md")):
        m = re.search(r"/reels?/([\w-]+)", open(f).read().split("---")[1])
        if m:
            out[m.group(1)] = f
    return out


def frontmatter(f):
    t = open(f).read()
    return t, t.split("---")[1]


def set_fields(f, fields):
    t, fm = frontmatter(f)
    for k in fields:
        fm = re.sub(rf"^{k}: .*\n", "", fm, flags=re.M)
    fm = "\n" + fm.strip("\n") + "\n" + "".join(f"{k}: {'null' if v is None else v}\n" for k, v in fields.items())
    open(f, "w").write(t.replace(t.split("---")[1], fm, 1))


def num(n):
    return f"{n:,}".replace(",", " ")


def table():
    rows = []
    for sid, f in sources().items():
        _, fm = frontmatter(f)
        g = lambda k: (re.search(rf"^{k}: (.*)$", fm, re.M) or [None, ""])[1].strip()
        v, l = g("views"), g("likes")
        rows.append((int(v) if v.isdigit() else None, int(l) if l.isdigit() else None, g("duration"),
                     g("published"), sid, re.split(r" \| | — | \(", g("author"))[0].strip(), g("kind")))
    rows.sort(key=lambda r: -(r[0] or 0))
    L = ["# Статистика разобранных рилсов", "",
         f"Просмотры и лайки из Instagram через Apify (`scripts/apify.py stats`), обновлено {date.today()}. "
         "Ролики моложе двух недель ещё набирают, со старыми их не сравнивать.", "",
         "| Рилс | Автор | Свой | Просмотры | Лайки | Лайки/просм. | Длина, с | Опубликован |",
         "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |"]
    for v, l, dur, d, sid, a, kind in rows:
        ratio = f"{100 * l / v:.1f} %" if v and l else "—"
        L.append(f"| {sid} | {a} | {'да' if kind == 'свой' else ''} | {num(v) if v else 'нет данных'} | "
                 f"{num(l) if l else '—'} | {ratio} | {float(dur or 0):.0f} | {d or '—'} |")
    open(os.path.join(ROOT, "stats.md"), "w").write("\n".join(L) + "\n")
    print(f"stats.md: {len(rows)} reels")


def stats(ids):
    src = sources()
    ids = ids or sorted(src)
    items = run_actor({"resultsType": "details", "resultsLimit": 1,
                       "directUrls": [f"https://www.instagram.com/p/{i}/" for i in ids]})
    got = {r["id"]: r for r in map(row, items) if r["id"]}
    for i in ids:
        r = got.get(i)
        if not r:
            print(f"{i}: нет данных (закрыт или удалён)")
            continue
        if i in src:
            set_fields(src[i], {"views": r["views"], "likes": r["likes"], "published": r["published"],
                                "stats_as_of": date.today()})
        print(f"{i}: {num(r['views']) if r['views'] else '—'} просмотров, {num(r['likes'] or 0)} лайков")
    table()


def own(user, n):
    items = run_actor({"resultsType": "reels", "resultsLimit": n,
                       "directUrls": [f"https://www.instagram.com/{user.lstrip('@')}/"]})
    rows = [r for r in map(row, items) if r["id"]]
    os.makedirs(os.path.join(ROOT, "work"), exist_ok=True)
    json.dump(rows, open(os.path.join(ROOT, "work", f"own-{user.lstrip('@')}.json"), "w"), ensure_ascii=False, indent=1)
    for r in sorted(rows, key=lambda r: -(r["views"] or 0)):
        print(f"{r['published']}  {num(r['views'] or 0):>11} просм.  {num(r['likes'] or 0):>8} лайков  "
              f"https://www.instagram.com/reel/{r['id']}/")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] not in ("stats", "own", "table"):
        sys.exit(__doc__)
    if a[0] == "table":
        table()
    elif a[0] == "stats":
        stats(a[1:])
    else:
        own(a[1], int(a[2]) if len(a) > 2 else 12)
