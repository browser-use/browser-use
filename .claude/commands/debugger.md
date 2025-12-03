---
description: Start a forensic CRASH-RCA debugging session for systematic root cause analysis.
argument-hint: [issue description]
---

# CRASH-RCA Debugging Protocol

You are the ORCHESTRATOR for a forensic debugging session using the CRASH-RCA protocol.

## Protocol Overview

**CRASH-RCA** = **C**ollect, **R**eason, **A**nalyze, **S**ynthesize, **H**andle

This protocol enforces:
1. **Read-Only Mode**: Write/Edit tools are blocked during investigation
2. **Logged Steps**: Every investigation action is recorded
3. **Evidence-Based**: Conclusions require concrete proof
4. **Structured Report**: Final diagnosis follows standard format

## Pipeline Overview

```plaintext
init-explorer → debugger → crash.py start → investigation → crash.py diagnose
```

## Your Execution Steps

### Step 1: Initialize with Context

Invoke `init-explorer` agent to:
1. Explore the target project structure
2. Read progress file (`claude-progress.txt`) for previous work
3. Read feature list (`feature_list.md`) to understand what's been implemented
4. Invoke the `debugger` agent automatically

```text
Task(subagent_type="init-explorer", prompt="
Explore this project and initialize context for the debugger workflow.

next_agent: debugger
task: $ARGUMENTS

After exploration:
1. Read claude-progress.txt to understand previous sessions
2. Read feature_list.md to understand implemented features
3. Update claude-progress.txt with this debugging session start
4. Invoke the debugger agent with the issue description
")
```

Wait for init-explorer to complete (it will invoke debugger internally).

### Step 2: CRASH Session (handled by debugger agent)

The debugger agent will:

1. **Start the CRASH session**:
   ```bash
   python3 .claude/scripts/crash.py start "$ARGUMENTS"
   ```

2. **Systematic Investigation** - For EACH action:
   ```bash
   python3 .claude/scripts/crash.py step \
     --hypothesis "What you think might be causing the issue" \
     --action "The specific tool/command you'll use to verify" \
     --confidence 0.X
   ```

3. **Execute investigation** using read-only tools:
   - `Grep` - Search for patterns in code
   - `Read` - Examine specific files
   - `Glob` - Find files by pattern
   - `Bash` - Run read-only commands (ls, cat, git log, etc.)

4. **Complete with Diagnosis** (when confidence > 0.8):
   ```bash
   python3 .claude/scripts/crash.py diagnose \
     --root_cause "One sentence summary of the defect" \
     --justification "Technical explanation of the failure mechanism" \
     --evidence "file:line; description; file:line; description"
   ```

### Step 3: Delegate if Needed

For complex investigations, use the Task tool to delegate:

- **Forensic Agent**: For targeted search operations
  ```text
  Task(subagent_type="forensic", prompt="Search for all database connection handling in src/")
  ```

- **Analyst Agent**: For synthesizing findings into diagnosis
  ```text
  Task(subagent_type="analyst", prompt="Review the investigation and prepare diagnosis")
  ```

## Investigation Patterns

### Error Investigation
1. Search for the exact error message
2. Trace to the throw/raise statement
3. Examine triggering conditions
4. Identify the defect

### Behavioral Issue
1. Identify what changed (git log)
2. Correlate changes with symptoms
3. Examine suspicious code
4. Verify with evidence

### Performance Issue
1. Look for bottleneck indicators
2. Check resource usage patterns
3. Find inefficient code paths
4. Measure and verify

## Critical Rules

**MUST DO:**
- Start with init-explorer for context
- Start every CRASH session with `crash.py start`
- Log every investigation step with `crash.py step`
- End with `crash.py diagnose`
- Include file:line references in evidence

**MUST NOT:**
- Use Write, Edit, or NotebookEdit (blocked in forensic mode)
- Skip logging investigation steps
- Draw conclusions without evidence
- End session without diagnosis

## Quality Gates

- Every hypothesis logged before investigation
- Confidence tracked throughout
- Evidence includes specific file:line references
- Root cause is actionable (can be fixed)
- Justification explains the failure chain

## Error Handling

If you encounter issues:
- Use `crash.py status` to check session state
- Use `crash.py cancel` if you need to abort
- Invoke the `stuck` agent for human guidance

## Session Flow Diagram

```plaintext
/debugger "issue"
    |
    v
init-explorer
    |-- Explore project structure
    |-- Read claude-progress.txt
    |-- Read feature_list.md
    |-- Update progress file
    |
    v
debugger agent
    |
    v
crash.py start --> Forensic Mode ON
    |
    v
+-> crash.py step (hypothesis)
|   |
|   v
|   Read/Grep/Glob/Bash (investigate)
|   |
|   v
|   Evaluate findings
|   |
|   v
+-- Confidence < 0.8? --> Loop back
    |
    | Confidence >= 0.8
    v
crash.py diagnose --> Report Generated
    |
    v
Forensic Mode OFF --> Session Complete
```

## Example Session

```plaintext
User: /debugger "Login API returns 500 intermittently"

1. init-explorer runs:
   - Explores project (Python Flask, PostgreSQL)
   - Reads progress: previous session implemented AUTH-001 through AUTH-005
   - Updates progress with debugging session start
   - Invokes debugger agent

2. debugger agent runs:
   crash.py start "Login API returns 500 intermittently"

3. Log hypothesis:
   crash.py step --hypothesis "Exception not being caught in auth handler" \
     --action "Search for try/catch in auth module" --confidence 0.3

4. Investigate:
   Grep for "except\|catch" in src/auth/

5. Log next hypothesis based on findings:
   crash.py step --hypothesis "Database timeout under load" \
     --action "Check connection pool config" --confidence 0.6

6. Read database config files...

7. Continue until confident...

8. Diagnose:
   crash.py diagnose \
     --root_cause "Connection pool size of 5 exhausted under concurrent load" \
     --justification "When >5 concurrent requests hit the login API, pool exhaustion causes timeout exceptions that bubble up as 500 errors" \
     --evidence "src/db/config.py:12 pool_size=5; logs/error.log 'connection timeout'; load test shows failure at 6+ concurrent users"
```

---

**Begin the investigation for: $ARGUMENTS**
