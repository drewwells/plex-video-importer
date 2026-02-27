#!/usr/bin/env python3
"""Reorganize 'westcoast - privates' files by instructor into named seasons.

Target layout:
  Season 01 - Elina/     S01E01-S01E10   image: ~/elina.jpg
  Season 02 - Glenn/     S02E01-S02E17   image: ~/glenn-baal-scc.jpg
  Season 03 - Others/    S03E01+

Phase 1 (filesystem) runs in dry-run unless --apply is given.
Phase 2 (Plex metadata) also requires --apply.

Token is read from env PLEX_TOKEN or from .plex_token in the project root.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import time
import urllib.parse
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHOW_NAME = "westcoast - privates"

SEASON_MAP: dict[str, tuple[int, str]] = {
    "elina": (1, "Elina"),
    "glenn": (2, "Glenn"),
}
OTHERS_SEASON = (3, "Others")

# Artwork: season_number -> path (None = skip)
ARTWORK: dict[int, pathlib.Path | None] = {
    1: pathlib.Path.home() / "elina.jpg",
    2: pathlib.Path.home() / "glenn-baal-scc.jpg",
    3: None,
}

# Pattern that matches "SxxEyy - <instructor> <rest>" in the stem.
# The separator before SxxEyy may be " - " or just " " (malformed files).
EPISODE_RE = re.compile(
    r"^(?P<show>.+?)\s+(?:-\s+)?S(?P<sn>\d{2})E(?P<ep>\d{2})\s+-\s+(?P<title>.+)$",
    re.IGNORECASE,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_token() -> str:
    token = os.environ.get("PLEX_TOKEN", "").strip()
    if token:
        return token
    tf = PROJECT_ROOT / ".plex_token"
    if tf.exists():
        return tf.read_text().strip()
    raise SystemExit("No PLEX_TOKEN env var and no .plex_token file found. Run plex_login.py first.")


def curl(url: str, token: str, method: str = "GET", extra_args: list[str] | None = None) -> bytes:
    cmd = ["curl", "-sS", "-L", "-H", f"X-Plex-Token: {token}", url]
    if method != "GET":
        cmd = ["curl", "-sS", "-L", "-X", method, "-H", f"X-Plex-Token: {token}", url]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.check_output(cmd)


def curl_post_file(url: str, token: str, file_path: pathlib.Path, content_type: str) -> bytes:
    cmd = [
        "curl", "-sS", "-L", "-X", "POST",
        "-H", f"X-Plex-Token: {token}",
        "-H", f"Content-Type: {content_type}",
        "--data-binary", f"@{file_path}",
        url,
    ]
    return subprocess.check_output(cmd)


_INSTRUCTOR_PREFIX_RE = re.compile(r"^(\w+)\s+(.+)$")


def classify_title(title: str) -> tuple[int, str, str]:
    """Return (season_num, season_label, stripped_title).

    For known instructors (elina/glenn) the instructor word is stripped.
    For Others, any single leading word is stripped as the instructor name.
    """
    lower = title.lower()
    for keyword, (snum, slabel) in SEASON_MAP.items():
        if lower.startswith(keyword):
            stripped = title[len(keyword):].lstrip(" -_").strip()
            return snum, slabel, stripped
    snum, slabel = OTHERS_SEASON
    # Strip leading instructor name (first word) from Others titles
    m = _INSTRUCTOR_PREFIX_RE.match(title)
    stripped = m.group(2) if m else title
    return snum, slabel, stripped


# ---------------------------------------------------------------------------
# Phase 1: filesystem
# ---------------------------------------------------------------------------

def collect_episodes(show_root: pathlib.Path) -> list[tuple[pathlib.Path, str, str, int]]:
    """Return list of (path, original_title, full_stem, original_ep_num) for all video files."""
    results = []
    for p in sorted(show_root.rglob("*")):
        if p.suffix.lower() not in (".mp4", ".mov"):
            continue
        m = EPISODE_RE.match(p.stem)
        if not m:
            print(f"  [SKIP] unrecognised filename: {p.name}")
            continue
        original_ep = int(m.group("ep"))
        title = m.group("title").strip()
        results.append((p, title, p.stem, original_ep))
    return results


def plan_reorganization(
    show_root: pathlib.Path,
    episodes: list[tuple[pathlib.Path, str, str, int]],
) -> list[tuple[pathlib.Path, pathlib.Path]]:
    """Return list of (src, dst) rename pairs."""
    show_stem = show_root.name  # "westcoast - privates"

    # Group by season
    buckets: dict[int, list[tuple[pathlib.Path, str, str]]] = {1: [], 2: [], 3: []}
    for path, title, stem, orig_ep in episodes:
        snum, slabel, stripped = classify_title(title)
        buckets[snum].append((path, stripped, f"Season {snum:02d} - {slabel}"))

    moves: list[tuple[pathlib.Path, pathlib.Path]] = []
    for snum in sorted(buckets):
        group = buckets[snum]
        slabel = {1: "Elina", 2: "Glenn", 3: "Others"}[snum]
        season_dir = show_root / f"Season {snum:02d} - {slabel}"
        for ep_idx, (src, stripped_title, _) in enumerate(group, start=1):
            new_name = f"{show_stem} - S{snum:02d}E{ep_idx:02d} - {stripped_title}{src.suffix}"
            dst = season_dir / new_name
            moves.append((src, dst))
    return moves


def apply_moves(moves: list[tuple[pathlib.Path, pathlib.Path]], dry_run: bool) -> None:
    created_dirs: set[pathlib.Path] = set()
    for src, dst in moves:
        if dst.parent not in created_dirs:
            if dry_run:
                print(f"  [mkdir] {dst.parent}")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
            created_dirs.add(dst.parent)
        print(f"  {'[DRY]' if dry_run else '[MOVE]'} {src.name}")
        print(f"         -> {dst.relative_to(src.parent.parent.parent)}")
        if not dry_run:
            src.rename(dst)


def remove_empty_dirs(show_root: pathlib.Path, dry_run: bool) -> None:
    """Remove Season 01 / Season 02 directories if now empty."""
    for candidate in sorted(show_root.iterdir()):
        if not candidate.is_dir():
            continue
        # Only touch the old flat seasons (no hyphen in name means old style)
        name = candidate.name
        if re.match(r"^Season \d{2}$", name):
            try:
                remaining = list(candidate.iterdir())
            except PermissionError:
                continue
            if not remaining:
                print(f"  {'[DRY rmdir]' if dry_run else '[rmdir]'} {name}")
                if not dry_run:
                    candidate.rmdir()
            else:
                print(f"  [KEEP] {name}/ — {len(remaining)} files remaining")


# ---------------------------------------------------------------------------
# Phase 2: Plex metadata
# ---------------------------------------------------------------------------

def find_show_key(server: str, section_id: str, show_title: str, token: str) -> str:
    url = (
        f"{server}/library/sections/{section_id}/all"
        f"?type=2&X-Plex-Container-Start=0&X-Plex-Container-Size=5000"
    )
    xml_bytes = curl(url, token)
    root = ET.fromstring(xml_bytes)
    for d in root.findall("Directory"):
        if d.get("title") == show_title:
            key = d.get("ratingKey") or d.get("key", "")
            if key.startswith("/library/metadata/"):
                key = key.split("/")[-1]
            return key
    raise SystemExit(f"Show not found in Plex: {show_title!r}")


def get_seasons(server: str, show_key: str, token: str) -> list[tuple[str, int]]:
    """Return list of (ratingKey, index) for season directories."""
    xml_bytes = curl(f"{server}/library/metadata/{show_key}/children", token)
    root = ET.fromstring(xml_bytes)
    seasons = []
    for d in root.findall("Directory"):
        if d.get("type") != "season":
            continue
        rk = d.get("ratingKey", "")
        idx_str = d.get("index", "")
        if rk and idx_str:
            seasons.append((rk, int(idx_str)))
    return seasons


def set_season_title(server: str, rk: str, title: str, token: str) -> None:
    q = urllib.parse.urlencode({"title.value": title, "title.locked": "1"})
    curl(f"{server}/library/metadata/{rk}?{q}", token, method="PUT")


def upload_artwork(server: str, rk: str, image_path: pathlib.Path, token: str) -> None:
    url = f"{server}/library/metadata/{rk}/posters"
    curl_post_file(url, token, image_path, "image/jpeg")


def plex_phase(
    server: str,
    section_id: str,
    show_title: str,
    token: str,
) -> None:
    # Refresh library
    print("\n[Plex] Triggering library refresh …")
    curl(f"{server}/library/sections/{section_id}/refresh", token)
    print("[Plex] Waiting 10s for Plex to index …")
    time.sleep(10)

    show_key = find_show_key(server, section_id, show_title, token)
    print(f"[Plex] show ratingKey={show_key}")

    seasons = get_seasons(server, show_key, token)
    season_names = {1: "Elina", 2: "Glenn", 3: "Others"}

    for rk, idx in sorted(seasons, key=lambda x: x[1]):
        if idx not in season_names:
            print(f"[Plex] Season {idx}: no mapping, skipping")
            continue
        name = season_names[idx]
        print(f"[Plex] Season {idx} ({rk}): setting title={name!r}")
        set_season_title(server, rk, name, token)

        artwork = ARTWORK.get(idx)
        if artwork and artwork.exists():
            print(f"[Plex] Season {idx}: uploading artwork {artwork}")
            upload_artwork(server, rk, artwork, token)
        elif artwork:
            print(f"[Plex] Season {idx}: artwork file not found: {artwork}")
        else:
            print(f"[Plex] Season {idx}: no artwork configured")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Reorganize westcoast - privates by instructor.")
    ap.add_argument("--shows-root", default="/mnt/raid/dance/Shows")
    ap.add_argument("--server", default="http://127.0.0.1:32400")
    ap.add_argument("--section-id", default="13")
    ap.add_argument("--show-title", default=SHOW_NAME)
    ap.add_argument("--apply", action="store_true", help="Actually move files and update Plex")
    args = ap.parse_args()

    show_root = pathlib.Path(args.shows_root) / args.show_title
    if not show_root.is_dir():
        raise SystemExit(f"Show directory not found: {show_root}")

    print(f"Show root: {show_root}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}\n")

    # Phase 1: filesystem
    episodes = collect_episodes(show_root)
    print(f"Found {len(episodes)} episode files\n")

    moves = plan_reorganization(show_root, episodes)
    print(f"Planned {len(moves)} moves:\n")
    apply_moves(moves, dry_run=not args.apply)

    if args.apply:
        print("\nRemoving now-empty old season directories:")
        remove_empty_dirs(show_root, dry_run=False)
    else:
        print("\n[DRY] Would remove empty Season NN directories after moves.")

    # Phase 2: Plex
    if not args.apply:
        print("\nRe-run with --apply to execute filesystem moves and update Plex metadata.")
        return

    token = load_token()
    plex_phase(args.server, args.section_id, args.show_title, token)
    print("\nDone.")


if __name__ == "__main__":
    main()
