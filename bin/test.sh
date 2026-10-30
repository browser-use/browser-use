#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
npm test
npm run build:python
export BROWSER_USE_NODE="${BROWSER_USE_NODE:-$(command -v node)}"
uv run --no-sync python -m unittest discover -s tests/python -v
uv run --no-sync pytest tests/ci "$@"
