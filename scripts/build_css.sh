#!/usr/bin/env bash
# Tailwind build + content hash + manifest emit.
# CWD must be repo root. Inputs: static/css/input.css + tailwind.config.js.
# Outputs: static/css/app.<hash>.css + static/css/manifest.json.
set -euo pipefail

INPUT="static/css/input.css"
TMP_OUT="static/css/app.css"

# Clean any stale hashed output before building (so shell globs don't pick them up)
rm -f static/css/app.*.css static/css/manifest.json

tailwindcss -i "$INPUT" -o "$TMP_OUT" --minify

HASH=$(sha256sum "$TMP_OUT" | awk '{print substr($1,1,12)}')
FINAL="static/css/app.${HASH}.css"
mv "$TMP_OUT" "$FINAL"

python3 - <<PY
import json, pathlib
pathlib.Path("static/css/manifest.json").write_text(json.dumps({
    "app.css": "app.${HASH}.css"
}, indent=2))
PY

echo "Built: ${FINAL}"
