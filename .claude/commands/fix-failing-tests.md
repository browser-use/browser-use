---
description: Run project tests and automatically fix any failures using the specialized agent.
---

# Fix Failing Tests Command

You must invoke the `fix-failing-tests` agent to run tests and fix any failures.

## Task

Use the Task tool to invoke the `fix-failing-tests` agent with the following details:

**Prompt**:
```text
Run the project's test suite and fix any failing tests.
At the end, report:
"Are all tests passing? [Yes/No]"
"Did fix-failing-tests agent attempt to fix all the tests? [Yes/No]"
```

## Logic

1.  Invoke the `fix-failing-tests` agent using the prompt above.
2.  Examine the agent's response for the line "Are all tests passing? No".
3.  If "Are all tests passing?" is "No", re-invoke the `fix-failing-tests` agent.
4.  Repeat this process until "Are all tests passing?" is "Yes" or you have reached a maximum of 3 attempts.
