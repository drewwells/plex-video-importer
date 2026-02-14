#!/usr/bin/env python3
"""Reorganize an already-downloaded JT Swing library into a single Plex show.

Input (current):
  <root>/JT Beginner/JT Beginner - S01E01 - Left Side Pass.mp4

Output:
  <root>/JTSwing/Season NN - <Category>/JTSwing - SNNEXX - <Title>.mp4

Rules:
- Category is derived from the folder name: strip leading "JT ".
- Season number is assigned by a preferred order list, then any extras alphabetically.
- Episode number is taken from filename E value.
- Episode title is taken from filename tail after " - S..E.. - ".
- Non-mp4 files are ignored.
- Does not overwrite; adds " (2)", " (3)" suffix if needed.
"""

from __future__ import annotations

import argparse
import os
import re

EP_RE = re.compile(r"^(?P<prefix>.+?) - S(?P<s>\d{2})E(?P<e>\d+) - (?P<title>.+?)\.mp4$")
WS_RE = re.compile(r"\s+")
INVALID_FS = re.compile(r"[\\/:*?\"<>|]")

PREFERRED_ORDER = [
    "Beginner",
    "Intermediate",
    "Advanced All-Star",
    "Drills",
    "Footwork",
    "Connection",
    "Musicality",
    "Concepts",
    "Old School Moves",
]


def safe_component(s: str) -> str:
    s = INVALID_FS.sub(" ", s)
    s = WS_RE.sub(" ", s).strip()
    return s


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="/mnt/raid/dance/jtswing.com")
    ap.add_argument("--show", default="JTSwing")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="jtswing_reorg_report.tsv")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    show = safe_component(args.show)

    # Collect categories from existing JT* dirs.
    cat_dirs = []
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if not os.path.isdir(p):
            continue
        if not name.startswith("JT "):
            continue
        cat = name[3:].strip()
        cat_dirs.append((cat, p))

    cats = [c for c, _ in cat_dirs]

    # Assign season numbers.
    season_order = []
    seen = set()
    for c in PREFERRED_ORDER:
        if c in cats and c not in seen:
            season_order.append(c)
            seen.add(c)
    for c in sorted(cats):
        if c not in seen:
            season_order.append(c)
            seen.add(c)
    season_num = {c: i + 1 for i, c in enumerate(season_order)}

    # Plan moves.
    planned = []  # (src, dst)
    skipped = []

    for cat, cdir in cat_dirs:
        for fn in sorted(os.listdir(cdir)):
            if not fn.endswith(".mp4"):
                continue
            m = EP_RE.match(fn)
            if not m:
                skipped.append(os.path.join(cdir, fn))
                continue

            ep = int(m.group("e"))
            title = m.group("title").strip()
            s = season_num[cat]

            ep_tag = f"{ep:02d}" if ep < 100 else str(ep)
            season_dir = safe_component(f"Season {s:02d} - {cat}")
            new_fn = safe_component(f"{show} - S{s:02d}E{ep_tag} - {title}.mp4")
            dst = unique_path(os.path.join(root, show, season_dir, new_fn))

            planned.append((os.path.join(cdir, fn), dst))

    if not args.apply:
        print(f"categories={len(cat_dirs)} seasons={len(season_order)} planned={len(planned)} skipped={len(skipped)}")
        for src, dst in planned[:20]:
            print(src)
            print(dst)
            print("--")
        if skipped:
            print("skipped sample:")
            for s in skipped[:20]:
                print(s)
        return

    os.makedirs(os.path.join(root, show), exist_ok=True)

    report_path = os.path.join(root, args.report)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("action\tsrc\tdst\n")
        for src, dst in planned:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)
            f.write(f"MOVE\t{src}\t{dst}\n")

    # Remove empty JT* dirs.
    for _cat, cdir in cat_dirs:
        try:
            if not os.listdir(cdir):
                os.rmdir(cdir)
        except OSError:
            pass

    print(f"moved={len(planned)} report={report_path}")


if __name__ == "__main__":
    main()
