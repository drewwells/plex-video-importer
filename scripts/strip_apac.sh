#!/usr/bin/env bash
#
# strip_apac.sh - Remux iPhone .mov files to .mp4 using the AAC track (drop APAC)
#
# Usage:
#   strip_apac.sh [INPUT] [OUTPUT_DIR]
#
#   INPUT       A single .mov file OR a directory containing .mov files.
#               Defaults to current directory if omitted.
#
#   OUTPUT_DIR  Where to put converted files.
#               - If INPUT is a directory:
#                   defaults to INPUT/converted
#               - If INPUT is a file:
#                   defaults to the file's directory
#
# Requirements:
#   - bash
#   - ffmpeg
#   - ffprobe
#
# Behavior:
#   - For each *.mov:
#       * Find the first audio stream with codec_name=aac
#       * If found, remux to <basename>.mp4 (no "_noapac")
#         with video copied, that AAC track copied, and any subtitles copied
#       * If no AAC track exists, the file is skipped with a warning
#       * Existing output files are not overwritten

set -euo pipefail

usage() {
  echo "Usage: $0 [INPUT] [OUTPUT_DIR]"
  echo
  echo "  INPUT can be either:"
  echo "    - a directory (process all .mov files in it), or"
  echo "    - a single .mov file (process only that file)."
  echo
  echo "  OUTPUT_DIR:"
  echo "    - If INPUT is a directory: defaults to INPUT/converted"
  echo "    - If INPUT is a file: defaults to the file's directory"
}

INPUT="${1:-.}"
OUTPUT_DIR="${2:-}"

if [[ "$INPUT" == "-h" || "$INPUT" == "--help" ]]; then
  usage
  exit 0
fi

# --- Check dependencies ---
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Error: ffmpeg not found in PATH" >&2
  exit 1
fi

if ! command -v ffprobe >/dev/null 2>&1; then
  echo "Error: ffprobe not found in PATH" >&2
  exit 1
fi

# Small helper to process one file
process_file() {
  local infile="$1"
  local outdir="$2"

  infile="$(realpath "$infile")"
  outdir="$(realpath -m "$outdir")"

  mkdir -p "$outdir"

  local base stem outfile
  base="$(basename "$infile")"
  stem="${base%.*}"
  outfile="$outdir/${stem}.mp4"

  if [[ -e "$outfile" ]]; then
    echo "Skipping '$base' → output exists: $(basename "$outfile")"
    return
  fi

  echo "Processing: $base"

  # Get first AAC audio stream index
  local aac_index
  aac_index="$(
    ffprobe -v error \
      -select_streams a \
      -show_entries stream=index,codec_name \
      -of csv=p=0 "$infile" \
    | awk -F',' '$2=="aac"{print $1; exit}'
  )"

  if [[ -z "$aac_index" ]]; then
    echo "  !! No AAC audio track found, skipping (probably APAC-only): $base"
    return
  fi

  echo "  Using AAC audio stream index: $aac_index"

  # Remux:
  #   - copy video
  #   - copy the chosen AAC audio stream
  #   - copy any subtitles if present (0:s? makes it optional)
  if ffmpeg -y -hide_banner -loglevel error \
    -i "$infile" \
    -map 0:v \
    -map 0:"$aac_index" \
    -map 0:s? \
    -c copy \
    "$outfile"; then
      echo "  -> Wrote: $(basename "$outfile")"
  else
      echo "  !! ffmpeg failed for: $base"
  fi

  echo
}

# --- Figure out if INPUT is a file or directory ---

if [[ -f "$INPUT" ]]; then
  # Single file mode
  FILE_PATH="$(realpath "$INPUT")"
  if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$(dirname "$FILE_PATH")"
  fi

  echo "Single file mode"
  echo "Input file : $FILE_PATH"
  echo "Output dir : $OUTPUT_DIR"
  echo

  process_file "$FILE_PATH" "$OUTPUT_DIR"

elif [[ -d "$INPUT" ]]; then
  # Directory mode
  INPUT_DIR="$(realpath "$INPUT")"
  if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$INPUT_DIR/converted"
  fi
  OUTPUT_DIR="$(realpath -m "$OUTPUT_DIR")"

  echo "Directory mode"
  echo "Input dir : $INPUT_DIR"
  echo "Output dir: $OUTPUT_DIR"
  echo

  shopt -s nullglob

  find "$INPUT_DIR" -maxdepth 1 -type f \( -iname '*.mov' -o -iname '*.MOV' \) -print0 |
  while IFS= read -r -d '' infile; do
    process_file "$infile" "$OUTPUT_DIR"
  done

  echo "Done. Check files in: $OUTPUT_DIR"
else
  echo "Error: INPUT '$INPUT' is neither a file nor a directory" >&2
  usage
  exit 1
fi
