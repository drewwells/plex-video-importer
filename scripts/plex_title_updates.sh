#!/bin/bash

TOKEN=''
SERVER='https://localhost:32400'

while IFS=$'\t' read -r rk qs; do
  curl -sS -L -k -X PUT -H "X-Plex-Token: $TOKEN" \
    "$SERVER/library/metadata/$rk?$qs" -o /dev/null
done < plex_title_updates.tsv
