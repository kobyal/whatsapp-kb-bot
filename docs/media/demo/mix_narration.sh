#!/usr/bin/env bash
# Mix Koby's recorded narration onto demo.mp4 -> demo-narrated.mp4
#
#   ./mix_narration.sh                      # auto: narration.m4a / narration.wav (one pass, aligned from t=0)
#   ./mix_narration.sh narration.m4a        # single-file mode, explicit file
#   ./mix_narration.sh --beats [DIR]        # per-beat mode: beat1.m4a .. beatN.m4a (or .wav) in DIR (default: .)
#                                           # beat k is placed at the start time of beat k in marks.json
#
# Loudness is normalised to -16 LUFS (loudnorm), audio is padded/trimmed to the video length, video is copied as-is.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VIDEO="$HERE/demo.mp4"; MARKS="$HERE/marks.json"; OUT="$HERE/demo-narrated.mp4"
LOUD="loudnorm=I=-16:TP=-1.5:LRA=11"

mode=single; file=""; dir="$HERE"
case "${1:-}" in
  --beats) mode=beats; dir="${2:-$HERE}" ;;
  "")  for f in narration.m4a narration.wav narration.mp3; do [ -f "$HERE/$f" ] && file="$HERE/$f" && break; done
       if [ -z "$file" ]; then
         if ls "$HERE"/beat1.* >/dev/null 2>&1; then mode=beats; else
           echo "no narration.m4a/.wav and no beat1.* found next to this script" >&2; exit 1; fi
       fi ;;
  *)   file="$1" ;;
esac

if [ "$mode" = single ]; then
  echo "single-file mode: $file"
  ffmpeg -y -v error -stats -i "$VIDEO" -i "$file" \
    -filter_complex "[1:a]${LOUD},apad[a]" -map 0:v -map "[a]" \
    -c:v copy -c:a aac -b:a 160k -shortest -movflags +faststart "$OUT"
else
  # beat start times (seconds) from marks.json, in order
  starts=($(python3 -c "import json;print(' '.join(str(m['start']) for m in json.load(open('$MARKS'))))"))
  n=${#starts[@]}; inputs=(); fc=""; mix=""
  k=0
  for i in $(seq 1 "$n"); do
    f=""; for ext in m4a wav mp3 aiff; do [ -f "$dir/beat$i.$ext" ] && f="$dir/beat$i.$ext" && break; done
    if [ -z "$f" ]; then echo "  beat$i: (missing, left silent)"; continue; fi
    ms=$(python3 -c "print(int(round(${starts[$((i-1))]}*1000)))")
    echo "  beat$i: $f @ ${starts[$((i-1))]}s"
    inputs+=(-i "$f"); k=$((k+1))
    fc="${fc}[$k:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=${ms}|${ms}[b$k];"; mix="${mix}[b$k]"
  done
  [ "$k" -gt 0 ] || { echo "no beat files found in $dir" >&2; exit 1; }
  fc="${fc}${mix}amix=inputs=$k:duration=longest:normalize=0,${LOUD},apad[a]"
  echo "per-beat mode: $k file(s)"
  ffmpeg -y -v error -stats -i "$VIDEO" "${inputs[@]}" -filter_complex "$fc" -map 0:v -map "[a]" \
    -c:v copy -c:a aac -b:a 160k -shortest -movflags +faststart "$OUT"
fi
echo "-> $OUT"; ffprobe -v error -show_entries stream=codec_type,codec_name:format=duration -of compact "$OUT"
