#!/bin/bash

# Post-Coder Standards Check Hook
# This hook runs automatically after the coder agent completes
# It triggers the coding-standards-checker agent to verify code quality

set -e

# Parse the hook input from stdin
HOOK_INPUT=$(cat)

# Extract session info
SESSION_ID=$(echo "$HOOK_INPUT" | jq -r '.session_id' 2>&1) || { echo "❌ Failed to parse session_id from input" >&2; exit 1; }
CWD=$(echo "$HOOK_INPUT" | jq -r '.cwd' 2>&1) || { echo "❌ Failed to parse cwd from input" >&2; exit 1; }
SUBAGENT_NAME=$(echo "$HOOK_INPUT" | jq -r '.subagent_name // empty' 2>&1) || { echo "❌ Failed to parse subagent_name from input" >&2; exit 1; }

# Validate SESSION_ID to prevent path traversal
if [[ "$SESSION_ID" =~ [^a-zA-Z0-9_-] ]]; then
  echo "❌ Invalid session_id: contains disallowed characters" >&2
  exit 1
fi

# Validate session_id format (alphanumeric, hyphen, underscore only)
if ! [[ "$SESSION_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "❌ Invalid session_id format" >&2
  exit 1
fi

# Validate CWD is not empty
if [ -z "$CWD" ]; then
  echo "❌ CWD is empty" >&2
  exit 1
fi

# Log hook execution
echo "🔍 Post-Coder Hook: Triggering coding standards check" >&2
echo "   Session: $SESSION_ID" >&2
echo "   Subagent: $SUBAGENT_NAME" >&2

# Only trigger if this is the coder agent
if [ "$SUBAGENT_NAME" != "coder" ]; then
  echo "   Skipping: Not a coder agent completion" >&2
  exit 0
fi

# Create a state file to track that coder has completed
STATE_DIR="$CWD/.claude/.state"
mkdir -p "$STATE_DIR"
echo "$(date -Iseconds)" > "$STATE_DIR/coder-completed-${SESSION_ID}"

# Output message to be shown in the transcript
cat <<EOF
{
  "continue": true,
  "systemMessage": "✅ Coder agent completed. Coding standards checker will be invoked automatically by the orchestrator."
}
EOF

exit 0
