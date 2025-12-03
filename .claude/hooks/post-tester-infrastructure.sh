#!/bin/bash

# Post-Tester Infrastructure Hook
# This hook runs automatically after the tester agent completes
# It triggers the bdd-test-runner agent to validate test infrastructure

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
echo "🏗️  Post-Tester Hook: Triggering test infrastructure validation" >&2
echo "   Session: $SESSION_ID" >&2
echo "   Subagent: $SUBAGENT_NAME" >&2

# Only trigger if this is the tester or backend-tester agent
if [ "$SUBAGENT_NAME" != "tester" ] && [ "$SUBAGENT_NAME" != "backend-tester" ] && [ "$SUBAGENT_NAME" != "frontend-tester" ]; then
  echo "   Skipping: Not a tester agent completion" >&2
  exit 0
fi

# Create a state file to track that testing has completed
STATE_DIR="$CWD/.claude/.state"
mkdir -p "$STATE_DIR"
echo "$(date -Iseconds)" > "$STATE_DIR/testing-completed-${SESSION_ID}"

# Output message to be shown in the transcript
cat <<EOF
{
  "continue": true,
  "systemMessage": "✅ Testing completed. BDD test runner will be invoked to validate test infrastructure (Dockerfile.test, Makefile test target, make test)."
}
EOF

exit 0
