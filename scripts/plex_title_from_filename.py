#!/usr/bin/env python3
"""Set Plex episode titles from the media file name.

Plex often shows generic "Episode 1" titles for personal media TV libraries.
This script:
- Lists episodes in a given library section
- For episodes whose media file path is under --files-root
- Sets the episode title to the parsed filename title and locks it

Auth: set env var PLEX_TOKEN.

Notes on connectivity:
- Home Plex servers can be flaky with many requests.
- We use curl with aggressive retry settings for both GET and PUT.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

TITLE_FROM_BASENAME_RE = [
    re.compile(r"^.+? - S\d{2}E\d+ - (?P<title>.+?)\.[^.]+$", re.IGNORECASE),
    re.compile(r"^S\d{2}E\d+ - (?P<title>.+?)\.[^.]+$", re.IGNORECASE),
]

CID_SUFFIX_RE = re.compile(r"\s*\(cid\s+[^)]+\)\s*$", re.IGNORECASE)
DUP_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")
BRACKET_ID_RE = re.compile(r"\s*\[[0-9]+\]\s*$")
WS_RE = re.compile(r"\s+")


def curl(url: str, token: str, method: str = "GET", quiet: bool = True, retry: int = 60) -> bytes:
    cmd = [
        "curl",
        "-sS",
        "-L",
        "-k",
        "--connect-timeout",
        "2",
        "--max-time",
        "30",
        "--retry",
        str(retry),
        "--retry-all-errors",
        "--retry-delay",
        "1",
        "-H",
        f"X-Plex-Token: {token}",
    ]
    if method != "GET":
        cmd += ["-X", method]
    cmd.append(url)

    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL if quiet else None)
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"curl failed: {method} {url}: {e}")


def get_section_id(server: str, library: str, token: str) -> str:
    data = curl(f"{server}/library/sections", token)
    root = ET.fromstring(data)
    for d in root.findall("Directory"):
        if d.get("title") == library:
            key = d.get("key")
            if key:
                return key
    raise SystemExit(f"library not found: {library}")


def fetch_episodes(server: str, section_id: str, token: str, page_size: int = 2000) -> list[ET.Element]:
    out: list[ET.Element] = []
    start = 0
    total = None

    while True:
        qs = urllib.parse.urlencode(
            {
                "type": "4",
                "X-Plex-Container-Start": str(start),
                "X-Plex-Container-Size": str(page_size),
            }
        )
        data = curl(f"{server}/library/sections/{section_id}/all?{qs}", token)
        root = ET.fromstring(data)

        if total is None:
            ts = root.get("totalSize")
            total = int(ts) if ts else None

        vids = root.findall("Video")
        if not vids:
            break
        out.extend(vids)

        start += len(vids)
        if total is not None and start >= total:
            break

    return out


def title_from_file_path(fp: str) -> str | None:
    base = os.path.basename(fp)
    for rx in TITLE_FROM_BASENAME_RE:
        m = rx.match(base)
        if m:
            t = m.group("title")
            t = BRACKET_ID_RE.sub("", t)
            t = CID_SUFFIX_RE.sub("", t)
            t = DUP_SUFFIX_RE.sub("", t)
            t = WS_RE.sub(" ", t).strip()
            return t or None

    name, _ = os.path.splitext(base)
    name = BRACKET_ID_RE.sub("", name)
    name = CID_SUFFIX_RE.sub("", name)
    name = DUP_SUFFIX_RE.sub("", name)
    name = WS_RE.sub(" ", name).strip()
    return name or None


def put_title(server: str, token: str, rating_key: str, title: str) -> None:
    q = urllib.parse.urlencode({"title.value": title, "title.locked": "1"})
    url = f"{server}/library/metadata/{rating_key}?{q}"
    curl(url, token, method="PUT", quiet=True, retry=60)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    ap.add_argument("--library", required=True)
    ap.add_argument("--section-id", default="", help="Optional: skip lookup and use this library section id")
    ap.add_argument("--files-root", required=True)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    token = os.environ.get("PLEX_TOKEN", "").strip()
    if not token:
        raise SystemExit("set PLEX_TOKEN env var")

    server = args.server.rstrip("/")
    files_root = os.path.abspath(args.files_root)

    section_id = args.section_id.strip() or get_section_id(server, args.library, token)

    if args.refresh:
        curl(f"{server}/library/sections/{section_id}/refresh", token)
        time.sleep(2)

    episodes = fetch_episodes(server, section_id, token)

    updates: list[tuple[str, str, str]] = []
    skipped = 0

    for v in episodes:
        rk = v.get("ratingKey")
        if not rk:
            continue
        part = v.find(".//Media/Part")
        if part is None:
            continue
        fp = part.get("file")
        if not fp:
            continue
        if not os.path.abspath(fp).startswith(files_root + os.sep):
            continue
        title = title_from_file_path(fp)
        if not title:
            skipped += 1
            continue
        updates.append((rk, fp, title))

    if args.limit and len(updates) > args.limit:
        updates = updates[: args.limit]

    if not args.apply:
        print(f"section_id={section_id}")
        print(f"episodes_in_section={len(episodes)}")
        print(f"candidate_updates={len(updates)}")
        print(f"skipped={skipped}")
        for rk, fp, title in updates[:10]:
            print(rk, os.path.basename(fp), "=>", title)
        return

    ok = 0
    for rk, fp, title in updates:
        try:
            put_title(server, token, rk, title)
            ok += 1
        except Exception as e:
            print(f"ERROR rk={rk} file={fp}: {e}", file=sys.stderr)

    print(f"updated={ok}")


if __name__ == "__main__":
    main()
