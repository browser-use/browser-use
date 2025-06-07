#!/usr/bin/env bash
# This script is used to run all the main project tests that run on CI via .github/workflows/test.yaml.
# Usage:
#   $ ./bin/test.sh

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$SCRIPT_DIR/.." || exit 1

exec uv run pytest -x --numprocesses auto tests/ci
