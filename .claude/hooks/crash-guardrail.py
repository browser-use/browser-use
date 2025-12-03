#!/usr/bin/env python3
"""
CRASH-RCA Guardrail Hook

Blocks write/edit operations when a CRASH debugging session is active.
This enforces "Forensic Mode" - read-only investigation until diagnosis.

This hook is triggered on PreToolUse events and reads JSON from stdin
in the Claude Code hook format.
"""
import sys
import os
import json

STATE_FILE = ".claude/.state/crash_state.json"

FORBIDDEN_TOOLS = [
    "Edit",
    "Write",
    "NotebookEdit",
]


def load_session():
    """Check if a CRASH session is active."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                if state.get('status') == 'active':
                    return state
        except (json.JSONDecodeError, IOError):
            pass
    return None


def main():
    try:
        input_data = sys.stdin.read()
        if not input_data or not input_data.strip():
            sys.exit(0)
        data = json.loads(input_data)
    except json.JSONDecodeError:
        sys.exit(0)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")

    session = load_session()
    if not session:
        sys.exit(0)

    if tool_name in FORBIDDEN_TOOLS:
        print(json.dumps({
            "error": (
                f"CRASH FORENSIC MODE: Tool '{tool_name}' is blocked.\n\n"
                f"Active Session: #{session['session_id']}\n"
                f"Issue: {session['issue']}\n\n"
                "You are restricted to Read-Only actions:\n"
                "- Read, Grep, Glob, Bash (read-only commands)\n\n"
                "To fix issues:\n"
                "1. Complete diagnosis with: python3 .claude/scripts/crash.py diagnose ...\n"
                "2. Or cancel session with: python3 .claude/scripts/crash.py cancel"
            )
        }))
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
