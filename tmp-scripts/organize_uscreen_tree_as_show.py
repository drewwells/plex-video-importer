#!/usr/bin/env python3
"""Organize an existing Uscreen download tree into a single Plex TV show.

Input example:
  <src_root>/Content/Basics 1/01 - Basics 1 - Sugar Push [1516845].mp4
  <src_root>/Self Technique/Dance Your Best Self/01 - ... [id].mp4

Output:
  <dst_root>/<show>/Season XX - <Category> - <Collection>/<show> - SXXEYY - <Title>.mp4

Defaults to hardlink (non-destructive).
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".m4v"}

LEADING_EP_RE = re.compile(r"^(?P<ep>\d{1,4})\s*[-_. ]\s*(?P<rest>.+)$")
BRACKET_ID_RE = re.compile(r"\s*\[[0-9]+\]\s*$")
INVALID_FS = re.compile(r"[\\/:*?\"<>|]")
WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Season:
    category: str
    collection: str
    dir_path: str


def safe_component(s: str) -> str:
    s = INVALID_FS.sub(" ", s)
    s = WS_RE.sub(" ", s).strip()
    return s


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def list_leaf_seasons(src_root: str) -> list[Season]:
    seasons: list[Season] = []
    for cat in sorted(os.listdir(src_root)):
        cat_path = os.path.join(src_root, cat)
        if not os.path.isdir(cat_path):
            continue
        # leaf collections are immediate subdirs
        for coll in sorted(os.listdir(cat_path)):
            coll_path = os.path.join(cat_path, coll)
            if not os.path.isdir(coll_path):
                continue
            vids = [
                os.path.join(coll_path, fn)
                for fn in os.listdir(coll_path)
                if os.path.isfile(os.path.join(coll_path, fn)) and is_video(os.path.join(coll_path, fn))
            ]
            if vids:
                seasons.append(Season(category=cat, collection=coll, dir_path=coll_path))
    return seasons


def parse_ep(base: str) -> int | None:
    m = LEADING_EP_RE.match(base)
    if not m:
        return None
    try:
        return int(m.group("ep"))
    except Exception:
        return None


def title_from_filename(base: str) -> str:
    name, _ext = os.path.splitext(base)
    name = BRACKET_ID_RE.sub("", name)
    m = LEADING_EP_RE.match(name)
    if m:
        name = m.group("rest")
    name = name.strip(" -_.")
    name = name.replace("_", " ")
    name = WS_RE.sub(" ", name).strip()
    return name or base


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def link_copy_move(src: str, dst: str, mode: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if mode == "hardlink":
        os.link(src, dst)
    elif mode == "copy":
        import shutil

        shutil.copy2(src, dst)
    elif mode == "move":
        os.rename(src, dst)
    else:
        raise SystemExit(f"unknown mode: {mode}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--show", required=True)
    ap.add_argument("--mode", choices=["hardlink", "copy", "move"], default="hardlink")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="uscreen_show_report.tsv")
    args = ap.parse_args()

    src_root = os.path.abspath(args.src)
    dst_root = os.path.abspath(args.dst)
    show = safe_component(args.show)

    seasons = list_leaf_seasons(src_root)

    report_path = os.path.join(dst_root, args.report)
    lines = ["action\tseason\tsrc\tdst"]

    for sidx, season in enumerate(seasons, 1):
        season_name = safe_component(f"Season {sidx:02d} - {season.category} - {season.collection}")
        season_dir = os.path.join(dst_root, show, season_name)

        files = sorted(
            [
                os.path.join(season.dir_path, fn)
                for fn in os.listdir(season.dir_path)
                if os.path.isfile(os.path.join(season.dir_path, fn)) and is_video(os.path.join(season.dir_path, fn))
            ]
        )

        # Determine episode numbers: respect leading numbers if present.
        extracted = [parse_ep(os.path.basename(f)) for f in files]
        have_any = any(e is not None for e in extracted)
        seq = 1

        for i, src in enumerate(files):
            base = os.path.basename(src)
            ep = extracted[i] if have_any else None
            if ep is None:
                ep = seq
                seq += 1

            ep_tag = f"{ep:02d}" if ep < 100 else str(ep)
            title = safe_component(title_from_filename(base))
            ext = os.path.splitext(base)[1]
            dst_name = safe_component(f"{show} - S{sidx:02d}E{ep_tag} - {title}{ext}")
            dst = unique_path(os.path.join(season_dir, dst_name))

            if args.apply:
                link_copy_move(src, dst, args.mode)
                lines.append(f"LINK\t{sidx:02d}\t{src}\t{dst}")
            else:
                lines.append(f"PLAN\t{sidx:02d}\t{src}\t{dst}")

    if args.apply:
        os.makedirs(dst_root, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    else:
        print(f"seasons: {len(seasons)}")
        print(f"report (on apply): {report_path}")


if __name__ == "__main__":
    main()
