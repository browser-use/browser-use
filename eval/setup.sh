#!/usr/bin/env bash
# Install this checkout's locked environment plus the eval-only renderers + Laminar (not product dependencies).
set -euo pipefail
uv sync --frozen --project "$EVAL_TARGET_DIR"
uv pip install --python "$EVAL_TARGET_DIR/.venv/bin/python" "lmnr>=0.8.6" "openpyxl==3.1.5" "pypdf==6.14.2"
"$EVAL_TARGET_DIR/.venv/bin/python" --version > "$EVAL_WORKSPACE/python.version"
sha256sum "$EVAL_TARGET_DIR/uv.lock" | cut -d ' ' -f 1 > "$EVAL_WORKSPACE/dependencies.sha256"
