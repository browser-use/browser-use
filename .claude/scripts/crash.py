#!/usr/bin/env python3
"""
CRASH-RCA State Manager

Manages debugging session state, logs investigation steps, and generates
Root Cause Analysis reports. This script serves as the "flight recorder"
for forensic debugging sessions.

Usage:
    python3 .claude/scripts/crash.py start "API 500 Error on login"
    python3 .claude/scripts/crash.py step --hypothesis "..." --action "..." --confidence 0.7
    python3 .claude/scripts/crash.py diagnose --root_cause "..." --justification "..." --evidence "..."
    python3 .claude/scripts/crash.py status
    python3 .claude/scripts/crash.py cancel
"""
import sys
import json
import argparse
import os
from datetime import datetime

STATE_DIR = ".claude/.state"
STATE_FILE = os.path.join(STATE_DIR, "crash_state.json")


def ensure_state_dir():
    """Ensure the state directory exists."""
    os.makedirs(STATE_DIR, exist_ok=True)


def load_state():
    """Load the current session state from disk."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return None


def save_state(state):
    """Save session state to disk."""
    ensure_state_dir()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def start_session(issue):
    """Initialize a new CRASH-RCA debugging session."""
    existing = load_state()
    if existing and existing.get('status') == 'active':
        print(f"ERROR: Session #{existing['session_id']} is already active.")
        print(f"Target: {existing['issue']}")
        print("Use 'crash.py cancel' to end it first, or 'crash.py diagnose' to complete it.")
        sys.exit(1)

    state = {
        "session_id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "started_at": datetime.now().isoformat(),
        "issue": issue,
        "steps": [],
        "status": "active"
    }
    save_state(state)

    print(f"CRASH-RCA Session #{state['session_id']} Started")
    print(f"Target: {issue}")
    print("")
    print("MODE: FORENSIC (Read-Only)")
    print("Write/Edit tools are DISABLED until diagnosis is complete.")
    print("")
    print("Next Steps:")
    print("1. Use 'crash.py step' to log each investigation hypothesis")
    print("2. Use Grep, Read, Bash (read-only commands) to investigate")
    print("3. Use 'crash.py diagnose' when you find the root cause")


def log_step(hypothesis, action, confidence):
    """Log an investigation step with hypothesis and planned action."""
    state = load_state()
    if not state or state['status'] != 'active':
        print("ERROR: No active CRASH session.")
        print("Run 'crash.py start \"issue description\"' first.")
        sys.exit(1)

    step_id = len(state['steps']) + 1
    new_step = {
        "id": step_id,
        "timestamp": datetime.now().isoformat(),
        "hypothesis": hypothesis,
        "action": action,
        "confidence": float(confidence)
    }
    state['steps'].append(new_step)
    save_state(state)

    print(f"Step {step_id} Logged")
    print("")
    print("--- INVESTIGATION HISTORY ---")

    for s in state['steps']:
        if s['confidence'] > 0.7:
            indicator = "HIGH"
        elif s['confidence'] > 0.4:
            indicator = "MED"
        else:
            indicator = "LOW"
        print(f"{s['id']}. [{indicator}] {s['hypothesis']}")
        print(f"   Action: {s['action']}")
    print("")

    if float(confidence) < 0.5:
        print("WARNING: Confidence is low.")
        print("Do not draw conclusions yet. Gather more evidence.")


def show_status():
    """Show current session status."""
    state = load_state()
    if not state:
        print("No CRASH-RCA session active.")
        print("Use 'crash.py start \"issue description\"' to begin.")
        return

    print(f"Session: #{state['session_id']}")
    print(f"Status: {state['status']}")
    print(f"Issue: {state['issue']}")
    print(f"Started: {state.get('started_at', 'unknown')}")
    print(f"Steps: {len(state['steps'])}")

    if state['steps']:
        print("")
        print("--- INVESTIGATION HISTORY ---")
        for s in state['steps']:
            if s['confidence'] > 0.7:
                indicator = "HIGH"
            elif s['confidence'] > 0.4:
                indicator = "MED"
            else:
                indicator = "LOW"
            print(f"{s['id']}. [{indicator}] {s['hypothesis']}")


def cancel_session():
    """Cancel the current session without diagnosis."""
    state = load_state()
    if not state:
        print("No active session to cancel.")
        return

    session_id = state['session_id']
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    print(f"Session #{session_id} cancelled.")
    print("Write/Edit tools are now re-enabled.")


def diagnose(root_cause, justification, evidence):
    """Complete the session with a root cause diagnosis."""
    state = load_state()
    if not state:
        print("ERROR: No session to diagnose.")
        print("Use 'crash.py start \"issue description\"' to begin a session.")
        sys.exit(1)

    evidence_items = [item.strip() for item in evidence.split(';') if item.strip()]

    print("# Root Cause Analysis Report")
    print("")
    print(f"**Session:** #{state['session_id']}")
    print(f"**Issue:** {state['issue']}")
    print(f"**Duration:** {state.get('started_at', 'unknown')} to {datetime.now().isoformat()}")
    print("")
    print("## Root Cause Summary")
    print("")
    print(root_cause)
    print("")
    print("## Justification")
    print("")
    print(justification)
    print("")
    print("## Evidence Chain")
    print("")
    for i, item in enumerate(evidence_items, 1):
        print(f"{i}. {item}")
    print("")
    print("## Investigation Steps")
    print("")
    for s in state['steps']:
        if s['confidence'] > 0.7:
            indicator = "HIGH"
        elif s['confidence'] > 0.4:
            indicator = "MED"
        else:
            indicator = "LOW"
        print(f"- **Step {s['id']}** [{indicator}]: {s['hypothesis']}")
        print(f"  - Action: {s['action']}")
    print("")
    print("---")
    print("")
    print("Session Complete. Write/Edit tools are now re-enabled.")

    os.remove(STATE_FILE)


def main():
    parser = argparse.ArgumentParser(
        description='CRASH-RCA State Manager for forensic debugging sessions'
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    start_parser = subparsers.add_parser('start', help='Start a new debugging session')
    start_parser.add_argument('issue', type=str, help='The symptom or issue being investigated')

    step_parser = subparsers.add_parser('step', help='Log an investigation step')
    step_parser.add_argument('--hypothesis', required=True, help='What theory are you testing?')
    step_parser.add_argument('--action', required=True, help='The command/tool you will run next')
    step_parser.add_argument(
        '--confidence',
        type=float,
        required=True,
        help='Confidence score 0.0 to 1.0'
    )

    subparsers.add_parser('status', help='Show current session status')

    subparsers.add_parser('cancel', help='Cancel current session without diagnosis')

    diag_parser = subparsers.add_parser('diagnose', help='Submit final root cause diagnosis')
    diag_parser.add_argument('--root_cause', required=True, help='One sentence summary of the defect')
    diag_parser.add_argument(
        '--justification',
        required=True,
        help='Technical explanation of the failure mechanism'
    )
    diag_parser.add_argument(
        '--evidence',
        required=True,
        help='Semicolon-separated list of proof (files, log lines, etc.)'
    )

    args = parser.parse_args()

    if args.command == 'start':
        start_session(args.issue)
    elif args.command == 'step':
        log_step(args.hypothesis, args.action, args.confidence)
    elif args.command == 'status':
        show_status()
    elif args.command == 'cancel':
        cancel_session()
    elif args.command == 'diagnose':
        diagnose(args.root_cause, args.justification, args.evidence)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
