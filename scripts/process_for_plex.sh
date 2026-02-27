#!/bin/bash
set -o pipefail

# Process movie files for Plex compatibility (Apple TV / iPhone)
# Uses hardware encoding when available:
#   - macOS: VideoToolbox
#   - Linux: Intel QSV (if available) or libx264 fallback

# Configuration
INPUT_DIR="${1:-.}"
OUTPUT_DIR="${INPUT_DIR}/processed"
EXTENSIONS=("mp4" "mkv" "avi" "mov" "wmv" "flv" "webm" "m4v" "mpeg" "mpg" "ts" "m2ts")

# Audio settings (AAC stereo for compatibility)
AUDIO_CODEC="aac"
AUDIO_BITRATE="192k"
AUDIO_CHANNELS="2"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check for ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    log_error "ffmpeg is not installed. Please install it first."
    exit 1
fi

# Detect OS and available hardware encoders
detect_encoder() {
    if [[ "$(uname)" == "Darwin" ]]; then
        echo "videotoolbox"
        return
    fi
    
    # Linux: check for Intel QSV support
    if ffmpeg -encoders 2>/dev/null | grep -q h264_qsv; then
        # Verify QSV actually works (driver + hardware present)
        if ffmpeg -hide_banner -init_hw_device qsv=hw -filter_hw_device hw -f lavfi -i nullsrc=s=256x256:d=1 -c:v h264_qsv -f null - 2>/dev/null; then
            echo "qsv"
            return
        fi
    fi
    
    # Linux: check for VAAPI support (alternative Intel/AMD hardware encoding)
    if ffmpeg -encoders 2>/dev/null | grep -q h264_vaapi; then
        if [[ -e /dev/dri/renderD128 ]]; then
            echo "vaapi"
            return
        fi
    fi
    
    # Fallback to software encoding
    echo "libx264"
}

ENCODER=$(detect_encoder)

case "$ENCODER" in
    videotoolbox)
        log_info "Using macOS VideoToolbox hardware encoder"
        VIDEO_OPTS="-c:v h264_videotoolbox -b:v 8M -profile:v high"
        ;;
    qsv)
        log_info "Using Intel Quick Sync (QSV) hardware encoder"
        VIDEO_OPTS="-c:v h264_qsv -global_quality 18 -profile:v high"
        ;;
    vaapi)
        log_info "Using VAAPI hardware encoder"
        VIDEO_OPTS="-vaapi_device /dev/dri/renderD128 -c:v h264_vaapi -qp 18 -profile:v high"
        VAAPI_FILTER="-vf format=nv12,hwupload"
        ;;
    libx264)
        log_info "Using libx264 software encoder (no hardware encoder detected)"
        VIDEO_OPTS="-c:v libx264 -preset medium -crf 18 -profile:v high -level:v 4.1"
        ;;
esac

# Validate input directory
if [[ ! -d "$INPUT_DIR" ]]; then
    log_error "Directory not found: $INPUT_DIR"
    exit 1
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"
log_info "Output directory: $OUTPUT_DIR"

# Build find pattern for extensions
find_pattern=""
for ext in "${EXTENSIONS[@]}"; do
    if [[ -n "$find_pattern" ]]; then
        find_pattern="$find_pattern -o"
    fi
    find_pattern="$find_pattern -iname *.$ext"
done

# Count files
file_count=$(find "$INPUT_DIR" -maxdepth 1 -type f \( $find_pattern \) 2>/dev/null | wc -l)
log_info "Found $file_count movie file(s) to process"

if [[ "$file_count" -eq 0 ]]; then
    log_warn "No movie files found in $INPUT_DIR"
    exit 0
fi

# Process each file
processed=0
failed=0

while IFS= read -r -d '' file; do
    filename=$(basename "$file")
    name="${filename%.*}"
    output_file="${OUTPUT_DIR}/${name}.mp4"
    
    # Skip if already processed
    if [[ -f "$output_file" ]]; then
        log_warn "Skipping (already exists): $filename"
        continue
    fi
    
    log_info "Processing: $filename"
    
    # Build ffmpeg command based on encoder
    if [[ "$ENCODER" == "vaapi" ]]; then
        # VAAPI needs special filter chain
        ffmpeg_cmd="ffmpeg -i \"$file\" $VIDEO_OPTS $VAAPI_FILTER -c:a $AUDIO_CODEC -b:a $AUDIO_BITRATE -ac $AUDIO_CHANNELS -movflags +faststart -map 0:v:0 -map 0:a:0? -y \"$output_file\""
    else
        ffmpeg_cmd="ffmpeg -i \"$file\" $VIDEO_OPTS -pix_fmt yuv420p -c:a $AUDIO_CODEC -b:a $AUDIO_BITRATE -ac $AUDIO_CHANNELS -movflags +faststart -map 0:v:0 -map 0:a:0? -y \"$output_file\""
    fi
    
    # Run ffmpeg
    if eval "$ffmpeg_cmd" </dev/null 2>&1 | tee -a "${OUTPUT_DIR}/ffmpeg.log"; then
        log_info "Completed: $name.mp4"
        ((processed++))
    else
        log_error "Failed to process: $filename"
        rm -f "$output_file"
        ((failed++))
    fi
    
done < <(find "$INPUT_DIR" -maxdepth 1 -type f \( $find_pattern \) -print0 2>/dev/null)

# Summary
echo ""
log_info "Processing complete!"
log_info "Processed: $processed file(s)"
[[ "$failed" -gt 0 ]] && log_error "Failed: $failed file(s)"
log_info "Output location: $OUTPUT_DIR"
