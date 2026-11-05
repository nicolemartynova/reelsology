#!/usr/bin/env python3
"""Rebuild CATALOG.md from the function cards, and check them.

    python3 scripts/catalog.py              # validate functions/*.md, rewrite CATALOG.md
    python3 scripts/catalog.py --next М     # next free ID in a category, e.g. М-04

A card's frontmatter needs id, name, category, sources; the ID must match its category and file
name, and be unique. The one-liner in the catalog is the card's «Суть» sentence.
"""
import glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATS = {"Х": "Хуки", "У": "Удержание", "М": "Монтаж", "Т": "Текст и субтитры",
        "Г": "Графика и движение", "З": "Звук", "С": "Сценарий и подача", "В": "Вкус"}


def front(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        k, _, v = line.partition(":")
        v = v.strip()
        out[k.strip()] = [x.strip() for x in v[1:-1].split(",") if x.strip()] if v.startswith("[") else v
    return out


cards, errors = [], []
for path in sorted(glob.glob(os.path.join(ROOT, "functions", "*.md"))):
    text = open(path).read()
    f = front(text)
    name = os.path.basename(path)
    for k in ("id", "name", "category", "sources"):
        if not f.get(k):
            errors.append(f"{name}: no {k}")
    fid = f.get("id", "")
    if fid and not name.startswith(fid + "-"):
        errors.append(f"{name}: file name must start with {fid}-")
    if fid and f.get("category") and not fid.startswith(f["category"] + "-"):
        errors.append(f"{name}: id {fid} is not in category {f['category']}")
    if f.get("category") and f["category"] not in CATS:
        errors.append(f"{name}: unknown category {f['category']}")
    m = re.search(r"\*\*Суть\.\*\*\s*(.+)", text)
    f["gist"] = m.group(1).strip() if m else ""
    cards.append(f)

ids = [c.get("id") for c in cards]
errors += [f"duplicate id {i}" for i in sorted({i for i in ids if i and ids.count(i) > 1})]

if "--next" in sys.argv:
    cat = sys.argv[sys.argv.index("--next") + 1]
    nums = [int(i.split("-")[1]) for i in ids if i and i.startswith(cat + "-")]
    print(f"{cat}-{max(nums, default=0) + 1:02d}")
    sys.exit(0)

L = ["# Каталог функций рилсологии", "",
     f"Всего функций: {len(cards)}. Источников: {len(glob.glob(os.path.join(ROOT, 'sources', '*.md')))}. "
     "Файл собирается скриптом `scripts/catalog.py`, руками не править.", ""]
for code, title in CATS.items():
    group = sorted((c for c in cards if c.get("category") == code), key=lambda c: c["id"])
    L.append(f"## {code} · {title} ({len(group)})")
    L.append("")
    if not group:
        L += ["пока нет", ""]
        continue
    for c in group:
        n = len(c.get("sources") or [])
        L.append(f"- **{c['id']}** {c['name']} — {c['gist']} _(рилсов: {n})_")
    L.append("")
open(os.path.join(ROOT, "CATALOG.md"), "w").write("\n".join(L))

print(f"CATALOG.md: {len(cards)} functions")
for e in errors:
    print("!!", e)
sys.exit(len(errors))
