#!/bin/zsh
set -euo pipefail

: "${PLEX_TOKEN:?set PLEX_TOKEN to your X-Plex-Token}"
: "${PLEX_SERVER:?set PLEX_SERVER, e.g. https://192.168.1.24:32400}"
: "${PLEX_LIBRARY:?set PLEX_LIBRARY, e.g. Dance}"
: "${FILES_ROOT:?set FILES_ROOT, e.g. /mnt/raid/dance}"

python3 /mnt/raid/dance/plex_title_from_filename.py \
  --server "$PLEX_SERVER" \
  --library "$PLEX_LIBRARY" \
  --files-root "$FILES_ROOT" \
  --refresh \
  --apply
