#!/usr/bin/env bash
# This script is used to run the formatter, linter, and type checker pre-commit hooks.
# Usage:
#   $ ./bin/lint.sh

IFS=$'\n'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

cd "$SCRIPT_DIR/.." || exit 1

echo "[*] Running ruff linter, formatter, and other pre-commit lint checks..."
uv run pre-commit run --all-files

echo "[*] Running pyright type checker..."
exec uv run pyright
