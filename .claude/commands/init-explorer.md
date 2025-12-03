---
description: Initialize project context by exploring codebase, reading progress history, and setting up feature tracking.
argument-hint: [optional: next workflow - architect|debugger]
---

# Project Initialization & Context Exploration

You are invoking the **init-explorer** agent to explore the codebase and set up context.

## Purpose

The init-explorer agent:
1. Orients to the project (pwd, ls, git status, git log)
2. Reads progress history (`claude-progress.txt`)
3. Reads feature list (`feature_list.md`)
4. Explores project structure via the Explore subagent
5. Creates example files if needed (`.feature_list.md.example`)
6. Updates progress file with session start
7. Optionally invokes the next workflow agent

## Execution

Invoke the init-explorer agent:

```text
Task(subagent_type="init-explorer", prompt="
Explore this project and initialize context.

next_agent: $ARGUMENTS
task: General project exploration and context setup

Steps to perform:
1. Orient yourself (pwd, ls -la, git log --oneline -10, git status)
2. Read claude-progress.txt if it exists
3. Read feature_list.md if it exists
4. Use Explore subagent for thorough codebase analysis
5. Create .feature_list.md.example if feature_list.md doesn't exist
6. Update claude-progress.txt with session start
7. If next_agent is specified (architect or debugger), invoke that agent
   Otherwise, report findings and complete

Report back:
- Tech stack discovered
- Project structure summary
- Features status (X/Y complete) if feature_list.md exists
- Progress history summary if claude-progress.txt exists
- Next steps or recommendations
")
```

## Arguments

- **No arguments**: Just explore and report (standalone mode)
- **architect**: After exploration, invoke architect agent for BDD-TDD workflow
- **debugger**: After exploration, invoke debugger agent for CRASH-RCA workflow

## Examples

### Standalone Exploration
```
/init-explorer
```
Explores the project and reports findings without starting a workflow.

### Start Architect Workflow
```
/init-explorer architect
```
Explores and then invokes the architect agent.

### Start Debugger Workflow
```
/init-explorer debugger
```
Explores and then invokes the debugger agent.

## Output

The agent will provide:
- Project tech stack and structure
- Git history summary
- Progress file contents (if exists)
- Feature list status (if exists)
- Session logged to `claude-progress.txt`

## Files Created/Updated

| File | Action |
|------|--------|
| `claude-progress.txt` | Created or appended with session info |
| `.feature_list.md.example` | Created if `feature_list.md` doesn't exist |

## Notes

- This command is typically called implicitly by `/architect` and `/debugger`
- Use standalone mode when you want to just explore without starting a workflow
- The progress file helps maintain context across sessions
