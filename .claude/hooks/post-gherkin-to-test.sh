#!/bin/bash

# Post-Gherkin-to-Test Hook
# This hook runs automatically after the gherkin-to-test agent completes
# It signals the orchestrator to invoke run-prompt with the created prompts

set -e

# Parse the hook input from stdin
HOOK_INPUT=$(cat)

# Extract session info
SESSION_ID=$(echo "$HOOK_INPUT" | jq -r '.session_id' 2>/dev/null) || { echo "Failed to parse session_id from input" >&2; exit 1; }
CWD=$(echo "$HOOK_INPUT" | jq -r '.cwd' 2>/dev/null) || { echo "Failed to parse cwd from input" >&2; exit 1; }
SUBAGENT_NAME=$(echo "$HOOK_INPUT" | jq -r '.subagent_name // empty' 2>/dev/null) || { echo "Failed to parse subagent_name from input" >&2; exit 1; }

# Validate session_id format (alphanumeric, hyphen, underscore only)
if ! [[ "$SESSION_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "Invalid session_id format" >&2
  exit 1
fi

# Validate CWD is not empty
if [ -z "$CWD" ]; then
  echo "CWD is empty" >&2
  exit 1
fi

# Validate CWD does not contain path traversal sequences
if [[ "$CWD" =~ \.\. ]]; then
  echo "Invalid CWD: path traversal detected" >&2
  exit 1
fi

# Log hook execution
echo "Post-Gherkin-to-Test Hook: Processing completion" >&2
echo "   Session: $SESSION_ID" >&2
echo "   Subagent: $SUBAGENT_NAME" >&2

# Only trigger if this is the gherkin-to-test agent
if [ "$SUBAGENT_NAME" != "gherkin-to-test" ]; then
  echo "   Skipping: Not a gherkin-to-test agent completion" >&2
  exit 0
fi

# Find BDD prompt files created by gherkin-to-test
PROMPTS_DIR="$CWD/prompts"
BDD_PROMPTS=""
PROMPT_COUNT=0

if [ -d "$PROMPTS_DIR" ]; then
  # Find prompts with bdd executor (files containing "executor: bdd")
  for file in "$PROMPTS_DIR"/*-bdd-*.md; do
    if [ -f "$file" ]; then
      # Extract just the number from the filename
      PROMPT_NUM=$(basename "$file" | grep -oE '^[0-9]+')
      if [ -n "$PROMPT_NUM" ]; then
        BDD_PROMPTS="$BDD_PROMPTS $PROMPT_NUM"
        PROMPT_COUNT=$((PROMPT_COUNT + 1))
      fi
    fi
  done
fi

# Trim leading space
BDD_PROMPTS=$(echo "$BDD_PROMPTS" | sed 's/^ //')

echo "   BDD prompt files found: $PROMPT_COUNT" >&2
echo "   Prompt numbers: $BDD_PROMPTS" >&2

# Create a state file to track that gherkin-to-test has completed
STATE_DIR="$CWD/.claude/.state"
mkdir -p "$STATE_DIR"
echo "$(date -Iseconds)" > "$STATE_DIR/gherkin-to-test-completed-${SESSION_ID}"

# Store prompt numbers for orchestrator reference
if [ -n "$BDD_PROMPTS" ]; then
  echo "$BDD_PROMPTS" > "$STATE_DIR/bdd-prompt-numbers-${SESSION_ID}"
fi

# Output message to be shown in the transcript
if [ $PROMPT_COUNT -gt 0 ]; then
  cat <<EOF
{
  "continue": true,
  "systemMessage": "Gherkin-to-test agent completed. Created $PROMPT_COUNT BDD prompt file(s). Run-prompt will be invoked automatically by the orchestrator with: run-prompt $BDD_PROMPTS --sequential"
}
EOF
else
  cat <<EOF
{
  "continue": true,
  "systemMessage": "Gherkin-to-test agent completed. Warning: No BDD prompt files found. Check if feature files exist in ./tests/bdd/"
}
EOF
fi

exit 0
