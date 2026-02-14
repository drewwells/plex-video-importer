#!/usr/bin/env bash
set -euo pipefail

if [[ "${DEBUG:-0}" == "1" ]]; then
  set -x
fi

# Batch transcode MP4 files to Apple TV / Plex-friendly MP4.
# Usage:
#   ./batch_transcode_plex_appletv.sh [MEDIA_DIR]
#
# Output files are created alongside inputs with ".plex-appletv.mp4" suffix.
# Existing outputs are skipped.

MEDIA_DIR="${1:-.}"

if [[ ! -d "${MEDIA_DIR}" ]]; then
  echo "Error: media directory not found: ${MEDIA_DIR}"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Error: ffmpeg is required but not found in PATH."
  exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
transcode_script="${script_dir}/transcode_plex_appletv.sh"

if [[ ! -x "${transcode_script}" ]]; then
  echo "Error: transcode script not found or not executable: ${transcode_script}"
  exit 1
fi

total=0
inspected=0
skipped=0
done_count=0
current_file=""

trap 'echo "ERROR: failed at file: ${current_file}"; echo "ERROR: line ${LINENO}"; exit 1' ERR

mapfile -d '' files < <(find "${MEDIA_DIR}" -type f -iname '*.mp4' -print0)
total="${#files[@]}"

for file in "${files[@]}"; do
  current_file="${file}"
  inspected=$((inspected + 1))
  percent=$((inspected * 100 / total))
  remaining=$((total - inspected))
  echo "[${inspected}/${total} ${percent}%] Inspecting: ${file} (remaining: ${remaining})"

  base_name="${file##*/}"
  if [[ "${base_name}" == *.plex-appletv.mp4 ]]; then
    skipped=$((skipped + 1))
    echo "  Skip: already a plex-appletv output"
    continue
  fi

  out_dir="${file%/*}"
  stem="${base_name%.*}"
  output="${out_dir}/${stem}.plex-appletv.mp4"

  if [[ -f "${output}" ]]; then
    skipped=$((skipped + 1))
    echo "  Skip: output exists"
    continue
  fi

  "${transcode_script}" "${file}" "${output}"
  done_count=$((done_count + 1))
done

echo "Batch transcode complete."
echo "Scanned: ${total}"
echo "Inspected: ${inspected}"
echo "Transcoded: ${done_count}"
echo "Skipped: ${skipped}"
