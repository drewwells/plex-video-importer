#!/usr/bin/env python3
"""Set Plex season titles based on on-disk season folder names.

Reads season directories under:
  --seasons-root (e.g. /mnt/raid/dance/garysusan/GarySusan or /mnt/raid/dance/jtswing.com/JTSwing)
Expected folder name pattern:
  Season NN - <Season Title>

Examples:
- GarySusan: "Season 01 - Basics 1 - Collection Name" -> season title "Basics 1 - Collection Name"
- JTSwing: "Season 01 - Beginner" -> season title "Beginner"

Then uses Plex API to:
- Find the show (--show-title) in the given library section
- Enumerate its seasons
- Set season title to "<Season Title>" and lock it

Requires env var PLEX_TOKEN.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET

SEASON_DIR_RE = re.compile(r"^Season\s+(?P<n>\d{2})\s+-\s+(?P<title>.+)$")


def curl(url: str, token: str, method: str = "GET") -> bytes:
    cmd = ["curl", "-sS", "-L", "-H", f"X-Plex-Token: {token}", url]
    if method != "GET":
        cmd = ["curl", "-sS", "-L", "-X", method, "-H", f"X-Plex-Token: {token}", url]
    return subprocess.check_output(cmd)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True, help="e.g. http://127.0.0.1:32400")
    ap.add_argument("--section-id", required=True, help="library section id (Dance is 13)")
    ap.add_argument("--show-title", default="GarySusan")
    ap.add_argument("--seasons-root", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("PLEX_TOKEN", "").strip()
    if not token:
        raise SystemExit("set PLEX_TOKEN")

    server = args.server.rstrip("/")
    section_id = args.section_id

    desired: dict[int, str] = {}
    for name in os.listdir(args.seasons_root):
        m = SEASON_DIR_RE.match(name)
        if not m:
            continue
        n = int(m.group("n"))
        title = m.group("title").strip()
        desired[n] = title

    if not desired:
        raise SystemExit("no seasons found on disk")

    shows_xml = curl(
        f"{server}/library/sections/{section_id}/all?type=2&X-Plex-Container-Start=0&X-Plex-Container-Size=5000",
        token,
    )
    root = ET.fromstring(shows_xml)

    show_key = None
    for d in root.findall("Directory"):
        if d.get("title") == args.show_title:
            show_key = d.get("ratingKey") or d.get("key")
            break
    if show_key and show_key.startswith("/library/metadata/"):
        show_key = show_key.split("/")[-1]

    if not show_key:
        raise SystemExit(f"show not found in Plex: {args.show_title}")

    seasons_xml = curl(f"{server}/library/metadata/{show_key}/children", token)
    sroot = ET.fromstring(seasons_xml)

    updates = []
    for d in sroot.findall("Directory"):
        if d.get("type") != "season":
            continue
        idx = d.get("index")
        rk = d.get("ratingKey")
        if not idx or not rk:
            continue
        n = int(idx)
        if n in desired:
            updates.append((rk, n, desired[n]))

    if not args.apply:
        print(f"show_key={show_key}")
        print(f"season_updates={len(updates)}")
        for rk, n, t in updates:
            print(n, rk, t)
        return

    for rk, n, t in updates:
        q = urllib.parse.urlencode({"title.value": t, "title.locked": "1"})
        url = f"{server}/library/metadata/{rk}?{q}"
        curl(url, token, method="PUT")

    print(f"updated_seasons={len(updates)}")


if __name__ == "__main__":
    main()
