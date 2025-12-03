# Claude Code Hooks

This directory contains hook scripts that automatically enforce quality gates during development.

## Hook Scripts

### 1. `post-coder-standards-check.sh`

**Trigger**: SubagentStop event when the `coder` agent completes

**Purpose**: Signals the orchestrator that the coding-standards-checker should be invoked

**Actions**:
- Validates the triggering agent is "coder"
- Creates state file: `.claude/.state/coder-completed-{session_id}`
- Outputs system message for the orchestrator

### 2. `post-standards-testing.sh`

**Trigger**: SubagentStop event when the `coding-standards-checker` agent completes

**Purpose**: Signals the orchestrator that the tester should be invoked

**Actions**:
- Validates the triggering agent is "coding-standards-checker"
- Creates state file: `.claude/.state/standards-checked-{session_id}`
- Outputs system message for the orchestrator

## Hook Configuration

Hooks are configured in `.claude/config.json`:

```json
{
  "hooks": {
    "SubagentStop": [...]
  }
}
```

## Testing Hooks

Test hooks manually:

```bash
# Test post-coder hook
echo '{"session_id":"test","cwd":"/root/repo","subagent_name":"coder"}' | \
  .claude/hooks/post-coder-standards-check.sh

# Test post-standards hook
echo '{"session_id":"test","cwd":"/root/repo","subagent_name":"coding-standards-checker"}' | \
  .claude/hooks/post-standards-testing.sh
```

## State Files

Hooks create state files in `.claude/.state/` for audit tracking:

- `coder-completed-{session_id}` - Timestamp when coder completed
- `standards-checked-{session_id}` - Timestamp when standards were verified

## Requirements

- `bash` - Shell interpreter
- `jq` - JSON parsing utility

## Documentation

See `/docs/HOOKS.md` for comprehensive documentation.
