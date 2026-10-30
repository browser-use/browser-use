#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
npm run check
npm run format:check
uv run --no-sync pre-commit run --all-files --show-diff-on-failure
