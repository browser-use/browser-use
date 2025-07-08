#!/usr/bin/env bash
# This script is used to run the formatter, linter, and type checker pre-commit hooks.
# Usage:
#   $ ./bin/lint.sh

IFS=$'\n'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

cd "$SCRIPT_DIR/.." || exit 1

echo "[*] Running ruff linter, formatter, pyright type checker, and other pre-commit checks..."
exec uv run pre-commit run --all-files
