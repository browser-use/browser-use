#!/usr/bin/env bash
# This script is used to run the formatter, linter, and type checker pre-commit hooks.
# Usage:
#   $ ./bin/lint.sh [OPTIONS]
#
# Options:
#   --fail-fast    Exit immediately on first failure (faster feedback)
#   --quick        Fast mode: skips pyright type checking (~2s vs 5s)
#   --staged       Check only staged files (for git pre-commit hook)
#
# Examples:
#   $ ./bin/lint.sh                    # Full check (matches CI/CD) - 5s
#   $ ./bin/lint.sh --quick            # Quick iteration (no types) - 2s
#   $ ./bin/lint.sh --staged           # Only staged files - varies
#   $ ./bin/lint.sh --staged --quick   # Fast pre-commit - <2s
#
# Note: 
#   - Quick mode skips type checking. Always run full mode before pushing to CI.
#   - This script runs tools directly from .venv to avoid 'uv run' permission errors.

set -o pipefail
IFS=$'\n'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$SCRIPT_DIR/.." || exit 1

# Find the active venv and prefer direct execution over uv run to avoid permission errors
if [ -n "$VIRTUAL_ENV" ]; then
    # Already in a venv, use tools directly
    RUN_CMD=""
elif [ -f ".venv/bin/activate" ]; then
    # Use .venv directly without activating
    RUN_CMD=".venv/bin/"
else
    # Fallback to uv run
    RUN_CMD="uv run "
fi

# Parse arguments
FAIL_FAST=0
QUICK_MODE=0
STAGED_MODE=0
for arg in "$@"; do
    case "$arg" in
        --fail-fast) FAIL_FAST=1 ;;
        --quick) QUICK_MODE=1 ;;
        --staged) STAGED_MODE=1 ;;
        *)
            echo "Unknown option: $arg"
            echo "Usage: $0 [--fail-fast] [--quick] [--staged]"
            exit 1
            ;;
    esac
done

# Create temp directory for logs
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Helper function to show spinner while waiting for process
spinner() {
    local pid=$1
    local name=$2
    local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
        i=$(( (i+1) %10 ))
        printf "\r[${spin:$i:1}] Running %s..." "$name"
        sleep 0.1
    done
    printf "\r"
}

# Helper to wait for job and handle result
wait_for_job() {
    local pid=$1
    local name=$2
    local logfile=$3
    local start_time=$4

    wait "$pid"
    local exit_code=$?
    local duration=$(($(date +%s) - start_time))

    if [ $exit_code -ne 0 ]; then
        printf "%-25s ❌ (%.1fs)\n" "$name" "$duration"
        if [ -s "$logfile" ]; then
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            cat "$logfile"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        fi
        return 1
    else
        printf "%-25s ✅ (%.1fs)\n" "$name" "$duration"
        return 0
    fi
}

# Build file list based on mode (compatible with sh and bash)
if [ $STAGED_MODE -eq 1 ]; then
    # Get staged Python files (files being committed)
    FILE_ARRAY=()
    while IFS= read -r file; do
        [ -n "$file" ] && FILE_ARRAY+=("$file")
    done <<EOF
$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null | grep '\.py$')
EOF

    if [ ${#FILE_ARRAY[@]} -eq 0 ]; then
        echo "[*] Staged mode: No Python files staged for commit"
        exit 0
    fi

    echo "[*] Staged mode: checking ${#FILE_ARRAY[@]} staged Python file(s)"
elif [ $QUICK_MODE -eq 1 ]; then
    # Get all changed Python files (staged and unstaged)
    FILE_ARRAY=()
    while IFS= read -r file; do
        [ -n "$file" ] && FILE_ARRAY+=("$file")
    done <<EOF
$(git diff --name-only --diff-filter=ACMR HEAD 2>/dev/null | grep '\.py$')
EOF

    if [ ${#FILE_ARRAY[@]} -eq 0 ]; then
        echo "[*] Quick mode: No Python files changed"
        exit 0
    fi

    echo "[*] Quick mode: checking ${#FILE_ARRAY[@]} changed Python file(s)"
else
    echo "[*] Full mode: checking all files (matches CI/CD exactly)"
    FILE_ARRAY=()
fi

echo ""
START_TIME=$(date +%s)

# Launch all checks in parallel
if [ ${#FILE_ARRAY[@]} -eq 0 ]; then
    # Full mode: check everything
    ${RUN_CMD}ruff check --fix > "$TEMP_DIR/ruff-check.log" 2>&1 &
    RUFF_CHECK_PID=$!
    RUFF_CHECK_START=$(date +%s)

    ${RUN_CMD}ruff format > "$TEMP_DIR/ruff-format.log" 2>&1 &
    RUFF_FORMAT_PID=$!
    RUFF_FORMAT_START=$(date +%s)

    ${RUN_CMD}pyright --threads 6 > "$TEMP_DIR/pyright.log" 2>&1 &
    PYRIGHT_PID=$!
    PYRIGHT_START=$(date +%s)

    SKIP=ruff-check,ruff-format,pyright ${RUN_CMD}pre-commit run --all-files > "$TEMP_DIR/other-checks.log" 2>&1 &
    OTHER_PID=$!
    OTHER_START=$(date +%s)
else
    # Staged or quick mode: check only specific files
    ${RUN_CMD}ruff check --fix "${FILE_ARRAY[@]}" > "$TEMP_DIR/ruff-check.log" 2>&1 &
    RUFF_CHECK_PID=$!
    RUFF_CHECK_START=$(date +%s)

    ${RUN_CMD}ruff format "${FILE_ARRAY[@]}" > "$TEMP_DIR/ruff-format.log" 2>&1 &
    RUFF_FORMAT_PID=$!
    RUFF_FORMAT_START=$(date +%s)

    # Pyright: skip in quick mode, run in staged mode
    if [ $QUICK_MODE -eq 1 ]; then
        echo "" > "$TEMP_DIR/pyright.log"
        PYRIGHT_PID=-1
        PYRIGHT_START=$(date +%s)
    else
        ${RUN_CMD}pyright --threads 6 "${FILE_ARRAY[@]}" > "$TEMP_DIR/pyright.log" 2>&1 &
        PYRIGHT_PID=$!
        PYRIGHT_START=$(date +%s)
    fi

    SKIP=ruff-check,ruff-format,pyright ${RUN_CMD}pre-commit run --files "${FILE_ARRAY[@]}" > "$TEMP_DIR/other-checks.log" 2>&1 &
    OTHER_PID=$!
    OTHER_START=$(date +%s)
fi

# Track failures
FAILED=0
FAILED_CHECKS=""

# Wait for each job in order of expected completion (fastest first)
# This allows --fail-fast to exit as soon as any check fails

# Ruff format is typically fastest
spinner $RUFF_FORMAT_PID "ruff format"
if ! wait_for_job $RUFF_FORMAT_PID "ruff format" "$TEMP_DIR/ruff-format.log" $RUFF_FORMAT_START; then
    FAILED=1
    FAILED_CHECKS="$FAILED_CHECKS ruff-format"
    if [ $FAIL_FAST -eq 1 ]; then
        kill $RUFF_CHECK_PID $PYRIGHT_PID $OTHER_PID 2>/dev/null
        wait $RUFF_CHECK_PID $PYRIGHT_PID $OTHER_PID 2>/dev/null
        echo ""
        echo "❌ Fast-fail: Exiting early due to ruff format failure"
        exit 1
    fi
fi

# Ruff check is second fastest
spinner $RUFF_CHECK_PID "ruff check"
if ! wait_for_job $RUFF_CHECK_PID "ruff check" "$TEMP_DIR/ruff-check.log" $RUFF_CHECK_START; then
    FAILED=1
    FAILED_CHECKS="$FAILED_CHECKS ruff-check"
    if [ $FAIL_FAST -eq 1 ]; then
        kill $PYRIGHT_PID $OTHER_PID 2>/dev/null
        wait $PYRIGHT_PID $OTHER_PID 2>/dev/null
        echo ""
        echo "❌ Fast-fail: Exiting early due to ruff check failure"
        exit 1
    fi
fi

# Pre-commit hooks are medium speed
spinner $OTHER_PID "other pre-commit hooks"
if ! wait_for_job $OTHER_PID "other pre-commit hooks" "$TEMP_DIR/other-checks.log" $OTHER_START; then
    FAILED=1
    FAILED_CHECKS="$FAILED_CHECKS pre-commit"
    if [ $FAIL_FAST -eq 1 ]; then
        kill $PYRIGHT_PID 2>/dev/null
        wait $PYRIGHT_PID 2>/dev/null
        echo ""
        echo "❌ Fast-fail: Exiting early due to pre-commit hooks failure"
        exit 1
    fi
fi

# Pyright is slowest (wait last for maximum parallelism)
if [ $PYRIGHT_PID -ne -1 ]; then
    spinner $PYRIGHT_PID "pyright"
    if ! wait_for_job $PYRIGHT_PID "pyright" "$TEMP_DIR/pyright.log" $PYRIGHT_START; then
        FAILED=1
        FAILED_CHECKS="$FAILED_CHECKS pyright"
    fi
else
    printf "%-25s ⏭️  (skipped in quick mode)\n" "pyright"
fi

TOTAL_TIME=$(($(date +%s) - START_TIME))

echo ""
if [ $FAILED -eq 1 ]; then
    echo "❌ Checks failed:$FAILED_CHECKS (${TOTAL_TIME}s total)"
    exit 1
fi

echo "✅ All checks passed! (${TOTAL_TIME}s total)"
exit 0
