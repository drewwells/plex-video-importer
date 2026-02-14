#!/usr/bin/env python3
"""Rename GarySusan episode files to remove duplicated collection prefix.

For a season directory named:
  Season NN - <Category> - <Collection>
we try to strip a leading "<Collection> -" / "<Collection>:" / "<Collection>：" from
"GarySusan - SNNEXX - <Title>.mp4".

Also strips trailing bracket IDs like "[12345]" if present.

Dry run by default; pass --apply to rename.
"""

from __future__ import annotations

import argparse
import os
import re

SEASON_DIR_RE = re.compile(r"^Season\s+(?P<n>\d{2})\s+-\s+(?P<cat>.+?)\s+-\s+(?P<coll>.+)$")
EP_FILE_RE = re.compile(r"^(?P<show>GarySusan) - S(?P<s>\d{2})E(?P<e>\d+) - (?P<title>.+)\.mp4$")
BRACKET_ID_RE = re.compile(r"\s*\[[0-9]+\]\s*$")
WS_RE = re.compile(r"\s+")


def candidate_prefixes(collection: str) -> list[str]:
    c = collection.strip()
    out = {c}

    # Common Uscreen naming: "X Volume 1" episodes often start with "X 1".
    out.add(re.sub(r"\bVolume\s+", "", c, flags=re.IGNORECASE).strip())

    # "and" vs "&"
    out.add(c.replace(" and ", " & "))
    out.add(c.replace(" & ", " and "))

    # Collapse whitespace
    out2 = set()
    for s in out:
        out2.add(WS_RE.sub(" ", s).strip())
    return [s for s in out2 if s]


def strip_prefix(title: str, prefixes: list[str]) -> str:
    t = title
    for p in prefixes:
        rx = re.compile(r"^" + re.escape(p) + r"\s*(?:-|:|：)\s*", re.IGNORECASE)
        if rx.search(t):
            return rx.sub("", t, count=1).strip()
    return t.strip()


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
    ap.add_argument("--root", required=True, help="/mnt/raid/dance/garysusan/GarySusan")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    root = os.path.abspath(args.root)

    planned = 0
    renamed = 0

    for season_dir in sorted(os.listdir(root)):
        s_path = os.path.join(root, season_dir)
        if not os.path.isdir(s_path):
            continue

        m = SEASON_DIR_RE.match(season_dir)
        if not m:
            continue

        coll = m.group("coll")
        prefixes = candidate_prefixes(coll)

        for fn in sorted(os.listdir(s_path)):
            if not fn.endswith(".mp4"):
                continue
            fm = EP_FILE_RE.match(fn)
            if not fm:
                continue

            title = fm.group("title")
            title = BRACKET_ID_RE.sub("", title).strip()
            new_title = strip_prefix(title, prefixes)
            new_title = WS_RE.sub(" ", new_title).strip()

            if new_title == title:
                continue

            new_fn = f"GarySusan - S{fm.group('s')}E{fm.group('e')} - {new_title}.mp4"
            src = os.path.join(s_path, fn)
            dst = unique_path(os.path.join(s_path, new_fn))

            planned += 1
            if args.apply:
                os.rename(src, dst)
                renamed += 1
            else:
                print(src)
                print(dst)
                print("--")

    if args.apply:
        print(f"renamed={renamed}")
    else:
        print(f"planned={planned}")


if __name__ == "__main__":
    main()
