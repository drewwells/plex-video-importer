#!/usr/bin/env python3
"""
Promote *.plex-appletv.mp4 variants so Plex will actually use them.

Typical situation:
- You have an original episode file:     <path>.mp4
- You created an Apple TV friendly file: <path>.plex-appletv.mp4
- Another workflow moved variants under: <root>/_variants/...

This script replaces the original with the Apple TV variant (renamed to .mp4),
and moves the original to: <root>/_variants/_replaced_originals/<relative_path>

Default is dry-run. Use --apply to make changes.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable


SUFFIX = ".plex-appletv.mp4"
SXXEXX_PREFIX = re.compile(r"^(?P<show>.+) - S(?P<s>\d{2})E(?P<e>\d{1,3}) - ")


@dataclass(frozen=True)
class PlanItem:
    variant: str
    original: str
    backup_original: str


def iter_files(root: str, *, under: str) -> Iterable[str]:
    base = os.path.join(root, under)
    if not os.path.isdir(base):
        return
    for dirpath, _, files in os.walk(base):
        for fn in files:
            yield os.path.join(dirpath, fn)


def ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def safe_rel(path: str, root: str) -> str:
    rel = os.path.relpath(path, root)
    # normalize for display/comparison
    return rel.replace(os.sep, "/")


def build_original_index(root: str, variants_dir: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for dirpath, _, files in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel == variants_dir or rel.startswith(variants_dir + os.sep):
            continue
        for fn in files:
            out[os.path.join(rel, fn)] = os.path.join(dirpath, fn)
    return out


def plan_promotions(
    root: str,
    variants_dir: str,
    backup_subdir: str,
    *,
    allow_basename_fallback: bool,
) -> tuple[list[PlanItem], list[str]]:
    root = os.path.abspath(root)
    idx = build_original_index(root, variants_dir)

    # Basename fallback: map expected original basename to candidate relpaths.
    by_base: dict[str, list[str]] = {}
    for relpath in idx.keys():
        by_base.setdefault(os.path.basename(relpath), []).append(relpath)

    plan: list[PlanItem] = []
    problems: list[str] = []

    for f in iter_files(root, under=variants_dir) or []:
        if not f.endswith(SUFFIX):
            continue

        rel = os.path.relpath(f, root)
        if not (rel == variants_dir or rel.startswith(variants_dir + os.sep)):
            continue

        rel_inside = rel[len(variants_dir) + 1 :]  # strip "<variants_dir>/"
        # Most common: variant mirrors the original relative path, but the
        # filename ends with ".plex-appletv.mp4" instead of ".mp4".
        candidate_rel = rel_inside[: -len(SUFFIX)] + ".mp4"
        original = idx.get(candidate_rel)

        if original is None:
            # Common case for GarySusan: the variant filename has extra prefixes/suffixes
            # (e.g. collection prefix, [cid]) that were removed from the canonical
            # on-disk Plex filename. Match by SxxEyy within the same directory.
            m = SXXEXX_PREFIX.match(os.path.basename(f))
            rel_dir = os.path.dirname(rel_inside)
            dir_full = os.path.join(root, rel_dir)
            if m and os.path.isdir(dir_full):
                show = m.group("show")
                s = m.group("s")
                e = int(m.group("e"))
                prefix = f"{show} - S{s}E{e:02d} - "
                cands = []
                for fn in os.listdir(dir_full):
                    if not fn.endswith(".mp4"):
                        continue
                    if fn.endswith(SUFFIX):
                        continue
                    if fn.startswith(prefix):
                        cands.append(fn)
                if len(cands) == 1:
                    original = os.path.join(dir_full, cands[0])
                elif len(cands) > 1:
                    problems.append(
                        "multiple originals match variant: "
                        + f"variant={safe_rel(f, root)} "
                        + f"dir={safe_rel(dir_full, root)} "
                        + f"matches={cands}"
                    )
                    continue

        if original is None and allow_basename_fallback:
            expected_base = os.path.basename(f)[: -len(SUFFIX)] + ".mp4"
            cands = by_base.get(expected_base, [])
            if len(cands) == 1:
                original = idx[cands[0]]

        if original is None:
            problems.append(f"no matching original for variant: {safe_rel(f, root)}")
            continue

        backup_original = os.path.join(root, variants_dir, backup_subdir, os.path.relpath(original, root))
        plan.append(PlanItem(variant=f, original=original, backup_original=backup_original))

    return plan, problems


def promote_one(p: PlanItem) -> None:
    if not os.path.exists(p.variant):
        raise FileNotFoundError(p.variant)
    if not os.path.exists(p.original):
        raise FileNotFoundError(p.original)
    if os.path.exists(p.backup_original):
        raise FileExistsError(p.backup_original)

    ensure_parent(p.backup_original)
    os.rename(p.original, p.backup_original)
    ensure_parent(p.original)
    os.rename(p.variant, p.original)


def promote_one_delete_original(p: PlanItem) -> None:
    # Overwrite the destination if it exists; this discards the original content.
    if not os.path.exists(p.variant):
        raise FileNotFoundError(p.variant)
    ensure_parent(p.original)
    os.replace(p.variant, p.original)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="e.g. /mnt/raid/dance/garysusan")
    ap.add_argument("--variants-dir", default="_variants")
    ap.add_argument("--backup-subdir", default="_replaced_originals")
    ap.add_argument("--no-basename-fallback", action="store_true", help="Require mirrored relative paths under _variants/")
    ap.add_argument("--delete-originals", action="store_true", help="Overwrite originals with variants (no backup kept)")
    ap.add_argument("--quiet", action="store_true", help="Only print summary and apply results (DONE/ERROR)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    plan, problems = plan_promotions(
        args.root,
        args.variants_dir,
        args.backup_subdir,
        allow_basename_fallback=not args.no_basename_fallback,
    )

    if not args.quiet:
        for s in problems:
            print("PROBLEM\t" + s)

    if not args.quiet:
        for p in plan:
            print(
                "PLAN\t"
                + f"variant={safe_rel(p.variant, args.root)}\t"
                + f"original={safe_rel(p.original, args.root)}\t"
                + f"backup_original={safe_rel(p.backup_original, args.root)}"
            )

    print(
        "summary\t"
        + f"variants_planned={len(plan)}\t"
        + f"problems={len(problems)}\t"
        + f"delete_originals={bool(args.delete_originals)}\t"
        + f"apply={bool(args.apply)}"
    )

    if not args.apply:
        return

    errors = 0
    for p in plan:
        try:
            if args.delete_originals:
                promote_one_delete_original(p)
            else:
                promote_one(p)
            print("DONE\t" + safe_rel(p.original, args.root))
        except Exception as e:
            errors += 1
            print("ERROR\t" + safe_rel(p.variant, args.root) + "\t" + str(e))

    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # Allow piping to `head`/`tail` without a traceback.
        sys.exit(0)
