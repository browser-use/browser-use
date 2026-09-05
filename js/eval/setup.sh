#!/usr/bin/env bash
# Build the exact target SDK; telemetry is a pinned dev dependency used only by this adapter.
set -euo pipefail
sdk_dir="$EVAL_TARGET_DIR"
npm --prefix "$sdk_dir" ci
npm --prefix "$sdk_dir" run build
node --version > "$EVAL_WORKSPACE/node.version"
sha256sum "$sdk_dir/package-lock.json" | cut -d ' ' -f 1 > "$EVAL_WORKSPACE/dependencies.sha256"
