#!/usr/bin/env python3
"""Create a Plex TV-show style tree from an existing category-organized directory.

Goal: make category folders become Plex 'Shows', with episodes under Season 01.

Default behavior is non-destructive: hardlink files into dest tree.

Heuristics for /mnt/raid/dance:
- Each top-level directory under source becomes a show.
- If a top-level dir contains both:
  - mp4s directly under it, and
  - mp4s under its immediate subdirs,
  then we split into multiple shows:
  - "<Top> - Misc" for the direct files
  - "<Top> - <Sub>" for each immediate subdir with mp4s

Episode numbering:
- If filename already contains SxxEyy, we keep yy.
- Else if it has a leading number like "01 - ..." we keep that.
- Else we assign sequential numbers by sorted path.

Episode title:
- Derived from filename, stripping common prefixes and suffixes.
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".m4v"}

SXXEXX_RE = re.compile(r"S(?P<s>\d{1,2})E(?P<e>\d{1,4})", re.IGNORECASE)
LEADING_NUM_RE = re.compile(r"^(?P<n>\d{1,4})\s*[-_. ]\s*(?P<rest>.+)$")
BRACKET_ID_RE = re.compile(r"\s*\[[0-9]+\]\s*$")
CID_RE = re.compile(r"\s*\(cid\s+[^)]+\)\s*$", re.IGNORECASE)
DUP_RE = re.compile(r"\s*\(\d+\)\s*$")

INVALID_FS = re.compile(r"[\\/:*?\"<>|]")
WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ShowGroup:
    name: str
    files: list[str]


def safe_component(s: str) -> str:
    s = INVALID_FS.sub(" ", s)
    s = WS_RE.sub(" ", s).strip()
    return s


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def list_videos_direct(dir_path: str) -> list[str]:
    out = []
    for fn in os.listdir(dir_path):
        p = os.path.join(dir_path, fn)
        if os.path.isfile(p) and is_video(p):
            out.append(p)
    return sorted(out)


def list_videos_recursive(dir_path: str) -> list[str]:
    out = []
    for dp, _, fns in os.walk(dir_path):
        for fn in fns:
            p = os.path.join(dp, fn)
            if os.path.isfile(p) and is_video(p):
                out.append(p)
    return sorted(out)


def parse_episode_number_from_filename(base: str) -> int | None:
    m = SXXEXX_RE.search(base)
    if m:
        try:
            return int(m.group("e"))
        except Exception:
            return None
    m = LEADING_NUM_RE.match(base)
    if m:
        try:
            return int(m.group("n"))
        except Exception:
            return None
    return None


def title_from_filename(base: str, show_name: str) -> str:
    name, _ext = os.path.splitext(base)
    name = BRACKET_ID_RE.sub("", name)
    name = CID_RE.sub("", name)
    name = DUP_RE.sub("", name)

    # Drop show prefix if present.
    if name.lower().startswith(show_name.lower() + " - "):
        name = name[len(show_name) + 3 :]

    # Drop SxxEyy patterns and separators before them.
    name = re.sub(r"^.*?\bS\d{1,2}E\d{1,4}\b\s*[-_. ]\s*", "", name, flags=re.IGNORECASE)

    # Drop leading number patterns.
    m = LEADING_NUM_RE.match(name)
    if m:
        name = m.group("rest")

    name = name.replace("_", " ").strip(" -_.")
    name = WS_RE.sub(" ", name).strip()
    return name or base


def hardlink_or_copy(src: str, dst: str, mode: str) -> None:
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


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def build_groups(source_root: str, dest_root: str) -> list[ShowGroup]:
    groups: list[ShowGroup] = []

    dest_base = os.path.basename(dest_root)

    for name in sorted(os.listdir(source_root)):
        if name in {dest_base, "_variants"}:
            continue
        if name.startswith("."):
            continue
        p = os.path.join(source_root, name)
        if not os.path.isdir(p):
            continue

        direct = list_videos_direct(p)
        subdirs = [
            os.path.join(p, d)
            for d in sorted(os.listdir(p))
            if os.path.isdir(os.path.join(p, d))
        ]
        sub_with_videos: list[tuple[str, list[str]]] = []
        for sd in subdirs:
            vids = list_videos_recursive(sd)
            if vids:
                sub_with_videos.append((sd, vids))

        if direct and sub_with_videos:
            groups.append(ShowGroup(name=f"{name} - Misc", files=direct))
            for sd, vids in sub_with_videos:
                subname = os.path.basename(sd)
                groups.append(ShowGroup(name=f"{name} - {subname}", files=vids))
        elif sub_with_videos and not direct:
            for sd, vids in sub_with_videos:
                subname = os.path.basename(sd)
                groups.append(ShowGroup(name=f"{name} - {subname}", files=vids))
        elif direct:
            groups.append(ShowGroup(name=name, files=direct))

    return groups


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--mode", choices=["hardlink", "copy", "move"], default="hardlink")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="dance_tvshows_report.tsv")
    args = ap.parse_args()

    source_root = os.path.abspath(args.source)
    dest_root = os.path.abspath(args.dest)

    groups = build_groups(source_root, dest_root)

    report_path = os.path.join(dest_root, args.report)
    lines = ["action\tshow\tsrc\tdst"]

    planned = 0
    for g in groups:
        show = safe_component(g.name)
        season_dir = os.path.join(dest_root, show, "Season 01")

        extracted = [parse_episode_number_from_filename(os.path.basename(f)) for f in g.files]
        have_any = any(e is not None for e in extracted)
        seq = 1

        for i, src in enumerate(g.files):
            base = os.path.basename(src)
            ep = extracted[i] if have_any else None
            if ep is None:
                ep = seq
                seq += 1

            ep_tag = f"{ep:02d}" if ep < 100 else str(ep)
            title = safe_component(title_from_filename(base, show))
            dst_name = safe_component(
                f"{show} - S01E{ep_tag} - {title}{os.path.splitext(base)[1]}"
            )
            dst = unique_path(os.path.join(season_dir, dst_name))

            planned += 1
            if args.apply:
                hardlink_or_copy(src, dst, args.mode)
                lines.append(f"LINK\t{show}\t{src}\t{dst}")
            else:
                lines.append(f"PLAN\t{show}\t{src}\t{dst}")

    if args.apply:
        os.makedirs(dest_root, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    else:
        print(f"groups: {len(groups)}")
        print(f"planned files: {planned}")
        print(f"report (on apply): {report_path}")


if __name__ == "__main__":
    main()
