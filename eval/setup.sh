#!/usr/bin/env bash
# Build the exact target SDK; telemetry is a pinned dev dependency used only by this adapter.
set -euo pipefail
sdk_dir="$EVAL_TARGET_DIR"
npm --prefix "$sdk_dir" ci
npm --prefix "$sdk_dir" run build
node --version > "$EVAL_WORKSPACE/node.version"
sha256sum "$sdk_dir/package-lock.json" | cut -d ' ' -f 1 > "$EVAL_WORKSPACE/dependencies.sha256"

# Findings evidence uses the same pinned workbook/PDF renderers as the bcode baseline.
if python3 -c 'import json,os,sys; sys.exit(json.loads(os.environ.get("EVAL_OPTIONS_JSON") or "{}").get("evidence_format") != "findings")'; then
  uv venv "$EVAL_WORKSPACE/.venv"
  uv pip install --python "$EVAL_WORKSPACE/.venv/bin/python" "openpyxl==3.1.5" "pypdf==6.14.2"
fi
