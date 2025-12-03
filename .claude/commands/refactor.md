---
description: Refactor existing code to adhere to coding standards while preserving functionality
argument-hint: [file-or-directory-path]
model: claude-3-5-sonnet-20241022
---

# Refactor Command

You must invoke the `refactorer` agent to refactor the code specified by the user.

## Task

Use the Task tool to invoke the `refactorer` subagent with the following details:

**subagent_type**: `refactorer`

**Prompt**:
```text
Refactor the code at: $ARGUMENTS

Analyze the specified file(s) or directory for coding standards violations and refactor the code to meet all standards while preserving functionality.

Follow the refactoring workflow:
1. Load coding standards from `.claude/coding-standards/`
2. Analyze current code for violations
3. Plan the refactoring approach
4. Execute refactoring step-by-step
5. Verify functionality preservation
6. Provide detailed refactoring report

If $ARGUMENTS is empty, analyze and refactor all code in the current project.
```

## Important

- Pass the file/directory path from $ARGUMENTS to the refactorer agent
- If no arguments provided, the refactorer should analyze the entire project
- The refactorer will handle all the details of the refactoring process
- The refactorer will invoke the stuck agent if issues arise
