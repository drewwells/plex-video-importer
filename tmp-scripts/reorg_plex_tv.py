#!/usr/bin/env python3
"""Reorganize downloaded videos into a Plex TV-show layout using a yt-dlp JSONL manifest.

Assumptions for Uscreen-derived manifests produced with `yt-dlp --dump-json`:
- Each line is a JSON object with `collection`, `category`, `collection_index`, `webpage_url`/`url`.
- `webpage_url` includes query params `cid` and `permalink`.
- Downloads are stored in per-collection directories, with filenames derived from permalink minus trailing `mp4`.

This script is intentionally conservative:
- It will not overwrite existing destination files.
- It records everything it does to a TSV report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse, parse_qs


INVALID_FS_CHARS = re.compile(r"[\\/:*?\"<>|]")
WS_RE = re.compile(r"\s+")
HEX_TOKEN_RE = re.compile(r"^[0-9a-f]{5,}$", re.IGNORECASE)


@dataclass(frozen=True)
class Entry:
    category: str | None
    collection: str | None
    playlist_index: int | None
    collection_index: int | None
    cid: str | None
    permalink: str | None


def safe_component(s: str) -> str:
    s = INVALID_FS_CHARS.sub(" ", s)
    s = WS_RE.sub(" ", s).strip()
    return s


def parse_manifest_jsonl(path: str) -> list[Entry]:
    out: list[Entry] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception as e:
                raise SystemExit(f"manifest parse error at {path}:{line_no}: {e}")

            u = obj.get("webpage_url") or obj.get("url")
            qs = parse_qs(urlparse(u).query) if u else {}
            cid = qs.get("cid", [None])[0]
            permalink = qs.get("permalink", [None])[0]

            out.append(
                Entry(
                    category=obj.get("category"),
                    collection=obj.get("collection"),
                    playlist_index=obj.get("playlist_index"),
                    collection_index=obj.get("collection_index"),
                    cid=cid,
                    permalink=permalink,
                )
            )
    return out


def choose_collection_dir(existing_dirs: set[str], collection: str) -> str | None:
    if collection in existing_dirs:
        return collection
    # common transforms
    cands = [
        collection.replace("/", "-"),
        collection.replace("/", " "),
        collection.replace("/", ""),
    ]
    for c in cands:
        if c in existing_dirs:
            return c
    # case-insensitive fallback
    low = {d.lower(): d for d in existing_dirs}
    if collection.lower() in low:
        return low[collection.lower()]
    for c in cands:
        if c.lower() in low:
            return low[c.lower()]
    return None


def permalink_to_base(permalink: str) -> str:
    s = permalink
    if s.endswith("mp4"):
        s = s[:-3]
    return s.strip("-_")


def title_from_permalink(permalink: str) -> str:
    base = permalink_to_base(permalink)
    parts = re.split(r"[-_]+", base)

    cleaned: list[str] = []
    for p in parts:
        if not p:
            continue
        lp = p.lower()
        if HEX_TOKEN_RE.fullmatch(lp):
            continue
        if lp in {"mov", "mp4"}:
            continue
        # e.g. 1080mov, 720p
        if re.fullmatch(r"\d+mov", lp) or re.fullmatch(r"\d+p\w*", lp):
            continue
        cleaned.append(p)

    if not cleaned:
        cleaned = [p for p in parts if p]

    out: list[str] = []
    for p in cleaned:
        if p.isupper() and len(p) <= 4:
            out.append(p)
        else:
            out.append(p[:1].upper() + p[1:])
    return " ".join(out)


def find_source_file(root: str, collection_dir: str, permalink: str, prefer_non_variants: bool) -> str | None:
    base = permalink_to_base(permalink)
    dpath = os.path.join(root, collection_dir)

    direct = os.path.join(dpath, base + ".mp4")
    if os.path.exists(direct):
        if prefer_non_variants and ".plex-appletv" in os.path.basename(direct):
            return None
        return direct

    # fallback: startswith match
    if not os.path.isdir(dpath):
        return None

    for fn in os.listdir(dpath):
        if not fn.endswith(".mp4"):
            continue
        if not fn.startswith(base):
            continue
        if prefer_non_variants and ".plex-appletv" in fn:
            continue
        return os.path.join(dpath, fn)

    return None


def ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def safe_rename(src: str, dst: str) -> None:
    ensure_parent(dst)
    os.rename(src, dst)


def iter_variant_files(root: str) -> Iterable[str]:
    for dirpath, _, files in os.walk(root):
        # Don't touch new layout roots.
        rel = os.path.relpath(dirpath, root)
        if rel == "TV Shows" or rel.startswith("TV Shows" + os.sep) or rel == "_variants" or rel.startswith("_variants" + os.sep):
            continue
        for fn in files:
            if fn.endswith(".plex-appletv.mp4"):
                yield os.path.join(dirpath, fn)


def iter_partials(root: str) -> Iterable[str]:
    for dirpath, _, files in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel == "TV Shows" or rel.startswith("TV Shows" + os.sep) or rel == "_variants" or rel.startswith("_variants" + os.sep):
            continue
        for fn in files:
            if ".part" in fn or fn.endswith(".ytdl"):
                yield os.path.join(dirpath, fn)


def strip_partial_suffix(path: str) -> str:
    # Handles:
    # - file.mp4.part
    # - file.mp4.part-Frag123.part
    # - file.mp4.part-Frag123
    if path.endswith(".ytdl"):
        path = path[:-5]
    return re.sub(r"\.part(?:-Frag\d+)?(?:\.part)?$", "", path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--show", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--move-variants", action="store_true", help="Move *.plex-appletv.mp4 into _variants/")
    ap.add_argument("--delete-safe-partials", action="store_true", help="Delete .part/.ytdl that have a completed .mp4 alongside")
    ap.add_argument("--report", default="reorg_report.tsv")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    manifest = os.path.abspath(args.manifest)
    show = args.show

    entries = parse_manifest_jsonl(manifest)

    existing_dirs = {d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))}

    # Season order by first appearance.
    season_order: list[str] = []
    seen: set[str] = set()
    for e in entries:
        if not e.collection:
            continue
        if e.collection not in seen:
            seen.add(e.collection)
            season_order.append(e.collection)
    season_num = {c: i + 1 for i, c in enumerate(season_order)}

    # Plan moves.
    planned: list[tuple[Entry, str, str]] = []
    missing: list[tuple[Entry, str]] = []
    dup_permalink: list[tuple[Entry, str]] = []
    seen_coll_permalink: set[tuple[str, str]] = set()

    for e in entries:
        if not e.collection or not e.permalink:
            missing.append((e, "missing_collection_or_permalink"))
            continue
        key = (e.collection, e.permalink)
        if key in seen_coll_permalink:
            # Uscreen sites can have multiple cids share a permalink; local downloads
            # are typically keyed by permalink, so only one file exists. Keep first.
            dup_permalink.append((e, "duplicate_collection_permalink"))
            continue
        seen_coll_permalink.add(key)

        cdir = choose_collection_dir(existing_dirs, e.collection)
        if not cdir:
            missing.append((e, "missing_collection_dir"))
            continue

        src = find_source_file(root, cdir, e.permalink, prefer_non_variants=True)
        if not src:
            missing.append((e, "missing_src"))
            continue

        s = season_num[e.collection]
        ep = int(e.collection_index or 0)
        title = title_from_permalink(e.permalink)

        season_dir = safe_component(f"Season {s:02d} - {e.collection}")
        fname = safe_component(f"{show} - S{s:02d}E{ep:02d} - {title}.mp4")
        dst = os.path.join(root, "TV Shows", show, season_dir, fname)
        planned.append((e, src, dst))

    # Destination conflict check.
    dst_counts = Counter(dst for _, _, dst in planned)
    conflicts = [dst for dst, n in dst_counts.items() if n > 1]
    if conflicts:
        raise SystemExit(f"refusing to proceed: {len(conflicts)} conflicting destination paths")

    # Build report.
    report_path = os.path.join(root, args.report)
    lines = []
    lines.append("action\tcollection\tcollection_index\tcid\tpermalink\tsrc\tdst\tnote")

    def record(action: str, e: Entry, src: str = "", dst: str = "", note: str = "") -> None:
        lines.append(
            "\t".join(
                [
                    action,
                    str(e.collection or ""),
                    str(e.collection_index or ""),
                    str(e.cid or ""),
                    str(e.permalink or ""),
                    src,
                    dst,
                    note,
                ]
            )
        )

    for e, why in missing:
        record("MISSING", e, note=why)
    for e, why in dup_permalink:
        record("SKIP", e, note=why)

    # Apply moves.
    for e, src, dst in planned:
        if not os.path.exists(src):
            if os.path.exists(dst):
                record("DONE", e, src, dst, note="src missing, dst exists")
            else:
                record("MISSING", e, src, dst, note="src missing at apply time")
            continue

        if os.path.exists(dst):
            # Don't overwrite; include cid to disambiguate.
            s = season_num[e.collection]  # type: ignore[arg-type]
            ep = int(e.collection_index or 0)
            title = title_from_permalink(e.permalink or "")
            cid = e.cid or "unknown"
            season_dir = safe_component(f"Season {s:02d} - {e.collection}")
            fname = safe_component(f"{show} - S{s:02d}E{ep:02d} - {title} (cid {cid}).mp4")
            alt = os.path.join(root, "TV Shows", show, season_dir, fname)
            if os.path.exists(alt):
                record("SKIP", e, src, dst, note="dst exists (and alt exists)")
                continue
            dst = alt

        if args.apply:
            try:
                safe_rename(src, dst)
                record("MOVE", e, src, dst)
            except FileNotFoundError as ex:
                record("MISSING", e, src, dst, note=str(ex))
            except OSError as ex:
                record("ERROR", e, src, dst, note=str(ex))
        else:
            record("PLAN", e, src, dst)

    # Optionally move variants.
    if args.move_variants:
        for src in iter_variant_files(root):
            rel = os.path.relpath(src, root)
            dst = os.path.join(root, "_variants", rel)
            if args.apply:
                ensure_parent(dst)
                safe_rename(src, dst)
                # variants aren't tied to a manifest entry
                lines.append("VARIANT_MOVE\t\t\t\t\t" + src + "\t" + dst + "\t")
            else:
                lines.append("VARIANT_PLAN\t\t\t\t\t" + src + "\t" + dst + "\t")

    # Optionally delete safe partials.
    if args.delete_safe_partials:
        for p in list(iter_partials(root)):
            base = strip_partial_suffix(p)
            if os.path.exists(base):
                if args.apply:
                    os.remove(p)
                    lines.append("PARTIAL_DELETE\t\t\t\t\t" + p + "\t\t")
                else:
                    lines.append("PARTIAL_PLAN_DELETE\t\t\t\t\t" + p + "\t\t")
            else:
                lines.append("PARTIAL_KEEP\t\t\t\t\t" + p + "\t\tno completed base")

    # Write report.
    if args.apply:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    else:
        # Print summary to stdout, and also write report next to root if possible.
        print(f"planned entries: {len(planned)}")
        print(f"missing entries: {len(missing)}")
        print(f"seasons: {len(season_order)} -> {season_order}")
        # best effort report write
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            print(f"report: {report_path}")
        except Exception as e:
            print(f"could not write report: {e}")


if __name__ == "__main__":
    main()
