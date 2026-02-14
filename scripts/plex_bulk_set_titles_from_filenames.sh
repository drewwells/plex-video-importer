#!/bin/zsh
set -euo pipefail

: "${PLEX_TOKEN:?set PLEX_TOKEN (X-Plex-Token)}"
: "${PLEX_SERVER:?set PLEX_SERVER (e.g. https://127.0.0.1:32400)}"
: "${PLEX_SECTION_ID:=13}"
: "${FILES_ROOT:?set FILES_ROOT (e.g. /mnt/raid/dance/Shows)}"

PAGE_SIZE=${PAGE_SIZE:-200}
SLEEP_BETWEEN_PUT=${SLEEP_BETWEEN_PUT:-0.05}

PLEX_SERVER=${PLEX_SERVER%/}

curl_get() {
  curl -sS -L -k \
    --connect-timeout 2 --max-time 60 \
    --retry 30 --retry-all-errors --retry-delay 1 \
    -H "X-Plex-Token: $PLEX_TOKEN" \
    "$1"
}

curl_put() {
  curl -sS -L -k \
    --connect-timeout 2 --max-time 60 \
    --retry 30 --retry-all-errors --retry-delay 1 \
    -X PUT -H "X-Plex-Token: $PLEX_TOKEN" \
    "$1" >/dev/null
}

meta_xml=$(curl_get "$PLEX_SERVER/library/sections/$PLEX_SECTION_ID/all?type=4&X-Plex-Container-Start=0&X-Plex-Container-Size=1")
total=$(printf '%s' "$meta_xml" | python3 - <<'PY'
import sys
import xml.etree.ElementTree as ET
root=ET.fromstring(sys.stdin.read())
print(int(root.get('totalSize') or 0))
PY
)

echo "total_episodes=$total" 1>&2

offset=0
updated=0

while [ $offset -lt $total ]; do
  xml=$(curl_get "$PLEX_SERVER/library/sections/$PLEX_SECTION_ID/all?type=4&X-Plex-Container-Start=$offset&X-Plex-Container-Size=$PAGE_SIZE")

  urls=$(printf '%s' "$xml" | FILES_ROOT="$FILES_ROOT" PLEX_SERVER="$PLEX_SERVER" python3 - <<'PY'
import os, re, sys, urllib.parse
import xml.etree.ElementTree as ET

files_root=os.path.abspath(os.environ['FILES_ROOT'])
server=os.environ['PLEX_SERVER'].rstrip('/')

rx1=re.compile(r'^.+? - S\\d{2}E\\d+ - (?P<title>.+?)\\.[^.]+$', re.I)
rx2=re.compile(r'^S\\d{2}E\\d+ - (?P<title>.+?)\\.[^.]+$', re.I)
cid=re.compile(r'\\s*\\(cid\\s+[^)]+\\)\\s*$', re.I)
dup=re.compile(r'\\s*\\(\\d+\\)\\s*$')
br=re.compile(r'\\s*\\[[0-9]+\\]\\s*$')
ws=re.compile(r'\\s+')

root=ET.fromstring(sys.stdin.read())
out=[]
for v in root.findall('Video'):
    rk=v.get('ratingKey')
    if not rk:
        continue
    part=v.find('.//Media/Part')
    if part is None:
        continue
    fp=part.get('file')
    if not fp:
        continue
    if not os.path.abspath(fp).startswith(files_root + os.sep):
        continue
    base=os.path.basename(fp)
    m=rx1.match(base) or rx2.match(base)
    if m:
        title=m.group('title')
    else:
        title=os.path.splitext(base)[0]
    title=br.sub('', title)
    title=cid.sub('', title)
    title=dup.sub('', title)
    title=ws.sub(' ', title).strip()
    if not title:
        continue
    qs=urllib.parse.urlencode({'title.value': title, 'title.locked': '1'})
    out.append(f"{server}/library/metadata/{rk}?{qs}")

sys.stdout.write("\\n".join(out))
PY
)

  if [ -n "$urls" ]; then
    while IFS= read -r url; do
      [ -z "$url" ] && continue
      curl_put "$url"
      updated=$((updated+1))
      sleep "$SLEEP_BETWEEN_PUT"
    done <<< "$urls"
  fi

  offset=$((offset+PAGE_SIZE))
  echo "progress offset=$offset updated=$updated" 1>&2
  sleep 0.2

done

echo "done updated=$updated" 1>&2
