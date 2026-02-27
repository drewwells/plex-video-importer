#!/usr/bin/env python3
"""Authenticate with plex.tv and save the auth token to .plex_token.

Usage:
    python3 scripts/plex_login.py
    python3 scripts/plex_login.py --username me@example.com --password secret

Token is written to <project_root>/.plex_token with chmod 600.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import pathlib
import stat
import subprocess
import sys
import uuid


PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN_FILE = PROJECT_ROOT / ".plex_token"

SIGNIN_URL = "https://plex.tv/api/v2/users/signin"
CLIENT_ID = str(uuid.uuid4())


def signin(username: str, password: str) -> str:
    cmd = [
        "curl", "-sS", "-X", "POST",
        "-H", f"X-Plex-Client-Identifier: {CLIENT_ID}",
        "-H", "X-Plex-Product: plex-video-importer",
        "-H", "X-Plex-Version: 1.0",
        "-H", "Accept: application/json",
        "--data-urlencode", f"login={username}",
        "--data-urlencode", f"password={password}",
        SIGNIN_URL,
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"curl failed: {e.stderr.decode()}")

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise SystemExit(f"unexpected response (not JSON):\n{out[:500].decode()}")

    if "errors" in data:
        msgs = "; ".join(e.get("message", str(e)) for e in data["errors"])
        raise SystemExit(f"plex.tv error: {msgs}")

    token = data.get("authToken") or data.get("user", {}).get("authToken")
    if not token:
        raise SystemExit(f"no authToken in response: {list(data.keys())}")
    return token


def save_token(token: str) -> None:
    TOKEN_FILE.write_text(token + "\n")
    TOKEN_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600


def main() -> None:
    ap = argparse.ArgumentParser(description="Authenticate with plex.tv and store token.")
    ap.add_argument("--username", help="Plex username or email")
    ap.add_argument("--password", help="Plex password (prompted if omitted)")
    args = ap.parse_args()

    username = args.username or input("Plex username/email: ").strip()
    password = args.password or getpass.getpass("Plex password: ")

    print("Signing in to plex.tv …", file=sys.stderr)
    token = signin(username, password)
    save_token(token)

    masked = token[:4] + "*" * max(0, len(token) - 8) + token[-4:]
    print(f"Token saved to {TOKEN_FILE}")
    print(f"Token: {masked}")


if __name__ == "__main__":
    main()
