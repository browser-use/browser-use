---
description: Investigate source code to verify claims, answer questions, or determine if user queries are true/false
argument-hint: [query-or-claim]
---

# Verifier Command

You must invoke the `verifier` agent to investigate the claim or question specified by the user.

## Task

Use the Task tool to invoke the `verifier` subagent with the following details:

**subagent_type**: `verifier`

**Prompt**:
```text
Investigate and verify: $ARGUMENTS

Explore the source code to verify the claim or answer the question above.

Follow the verification workflow:
1. Understand the query or claim being investigated
2. Plan a memory-efficient search strategy (search before reading)
3. Gather evidence from the codebase
4. Formulate a determination (TRUE/FALSE/PARTIALLY TRUE/CANNOT DETERMINE)
5. Provide a structured verification report with evidence

Use progressive narrowing:
- Start with Glob/Grep to find relevant files
- Use Grep with content mode to see code snippets
- Read only the most relevant files for evidence
- Include file paths, line numbers, and code snippets in your report

If $ARGUMENTS is empty, ask the user what they would like you to verify.
```

## Important

- Pass the query/claim from $ARGUMENTS to the verifier agent
- If no arguments provided, the verifier should request clarification
- The verifier will handle all details of the investigation process
- The verifier will invoke the stuck agent if the query is ambiguous or evidence is insufficient
