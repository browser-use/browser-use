#!/bin/bash

# Post-BDD-Agent Hook
# This hook runs automatically after the bdd-agent completes
# It signals the orchestrator to invoke the gherkin-to-test agent

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
echo "Post-BDD-Agent Hook: Processing completion" >&2
echo "   Session: $SESSION_ID" >&2
echo "   Subagent: $SUBAGENT_NAME" >&2

# Only trigger if this is the bdd-agent
if [ "$SUBAGENT_NAME" != "bdd-agent" ]; then
  echo "   Skipping: Not a bdd-agent completion" >&2
  exit 0
fi

# Verify BDD artifacts exist
BDD_DIR="$CWD/tests/bdd"

if [ ! -d "$BDD_DIR" ]; then
  echo "   Warning: BDD directory not found at $BDD_DIR" >&2
fi

# Count feature files
FEATURE_COUNT=$(find "$BDD_DIR" -name "*.feature" 2>/dev/null | wc -l)
echo "   Feature files found: $FEATURE_COUNT" >&2

# Create a state file to track that bdd-agent has completed
STATE_DIR="$CWD/.claude/.state"
mkdir -p "$STATE_DIR"
echo "$(date -Iseconds)" > "$STATE_DIR/bdd-agent-completed-${SESSION_ID}"

# Output message to be shown in the transcript
cat <<EOF
{
  "continue": true,
  "systemMessage": "BDD Agent completed. Found $FEATURE_COUNT feature file(s). Scope-Manager will be invoked automatically."
}
EOF

exit 0
