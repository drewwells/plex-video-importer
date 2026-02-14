#!/usr/bin/env bash
set -euo pipefail

# Transcode a single input video to an Apple TV / Plex-friendly MP4.
#
# Usage:
#   ./transcode_plex_appletv.sh <input_video> [output_mp4]
#
# Examples:
#   ./transcode_plex_appletv.sh "input.mkv"
#   ./transcode_plex_appletv.sh "input.mov" "output_appletv.mp4"
#
# Tunables via env vars:
#   CRF=20                # Lower = higher quality, larger file (libx264)
#   PRESET=medium         # ultrafast..veryslow
#   AUDIO_BITRATE=192k    # AAC bitrate
#   MAX_WIDTH=1920        # Keep source size if already smaller
#   USE_QSV=0             # 1 to use Intel Quick Sync (h264_qsv)
#   QSV_QUALITY=23        # Lower = higher quality (h264_qsv)
#
# Notes:
# - Produces H.264 High@4.1, yuv420p, AAC-LC stereo in MP4.
# - Uses +faststart for better streaming behavior.
# - This script keeps only the first video stream and first audio stream.

INPUT_FILE="${1:-}"
OUTPUT_FILE="${2:-}"

if [[ -z "${INPUT_FILE}" ]]; then
  echo "Usage: $0 <input_video> [output_mp4]"
  exit 1
fi

if [[ ! -f "${INPUT_FILE}" ]]; then
  echo "Error: input file not found: ${INPUT_FILE}"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Error: ffmpeg is required but not found in PATH."
  exit 1
fi

CRF="${CRF:-20}"
PRESET="${PRESET:-medium}"
AUDIO_BITRATE="${AUDIO_BITRATE:-192k}"
MAX_WIDTH="${MAX_WIDTH:-1920}"
USE_QSV="${USE_QSV:-0}"
QSV_QUALITY="${QSV_QUALITY:-23}"

if [[ -z "${OUTPUT_FILE}" ]]; then
  base_name="${INPUT_FILE##*/}"
  stem="${base_name%.*}"
  OUTPUT_FILE="${stem}.plex-appletv.mp4"
fi

out_dir="${OUTPUT_FILE%/*}"
if [[ "${out_dir}" != "${OUTPUT_FILE}" ]]; then
  mkdir -p "${out_dir}"
fi

echo "Input:  ${INPUT_FILE}"
echo "Output: ${OUTPUT_FILE}"
if [[ "${USE_QSV}" == "1" ]]; then
  echo "Video:  h264_qsv high@4.1 nv12 QSV_QUALITY=${QSV_QUALITY}"
else
  echo "Video:  libx264 high@4.1 yuv420p CRF=${CRF} preset=${PRESET}"
fi
echo "Audio:  aac ${AUDIO_BITRATE} stereo"

if [[ "${USE_QSV}" == "1" ]]; then
  if ! ffmpeg -hide_banner -nostdin -n \
      -i "${INPUT_FILE}" \
      -map 0:v:0 -map 0:a:0? \
      -c:v h264_qsv \
      -global_quality "${QSV_QUALITY}" \
      -profile:v high \
      -level:v 4.1 \
      -vf "scale='min(iw,${MAX_WIDTH})':-2:flags=lanczos,format=nv12" \
      -c:a aac \
      -b:a "${AUDIO_BITRATE}" \
      -ac 2 \
      -movflags +faststart \
      "${OUTPUT_FILE}"; then
    echo "WARN: QSV failed, falling back to libx264 for ${INPUT_FILE}"
    rm -f "${OUTPUT_FILE}"
    ffmpeg -hide_banner -nostdin -n \
      -i "${INPUT_FILE}" \
      -map 0:v:0 -map 0:a:0? \
      -c:v libx264 \
      -preset "${PRESET}" \
      -crf "${CRF}" \
      -profile:v high \
      -level:v 4.1 \
      -pix_fmt yuv420p \
      -vf "scale='min(iw,${MAX_WIDTH})':-2:flags=lanczos" \
      -c:a aac \
      -b:a "${AUDIO_BITRATE}" \
      -ac 2 \
      -movflags +faststart \
      "${OUTPUT_FILE}"
  fi
else
  ffmpeg -hide_banner -nostdin -n \
    -i "${INPUT_FILE}" \
    -map 0:v:0 -map 0:a:0? \
    -c:v libx264 \
    -preset "${PRESET}" \
    -crf "${CRF}" \
    -profile:v high \
    -level:v 4.1 \
    -pix_fmt yuv420p \
    -vf "scale='min(iw,${MAX_WIDTH})':-2:flags=lanczos" \
    -c:a aac \
    -b:a "${AUDIO_BITRATE}" \
    -ac 2 \
    -movflags +faststart \
    "${OUTPUT_FILE}"
fi

echo "Done."
