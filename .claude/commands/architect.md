---
description: Implements a feature using the Strict Spec-Analyst-Test-Implement pipeline.
argument-hint: [feature description]
---

# Spec-Driven Feature Implementation with BDD

You are the ORCHESTRATOR for the BDD-TDD pipeline. Use the Task tool to execute the following pipeline sequentially, responding to hook signals between phases.

## Pipeline Overview

```plaintext
init-explorer → Architect → BDD-Agent → Scope-Manager 
   ↓ (TRIVIAL) → strict-coder → END
   ↓ (PASS)
Requirements-QA → (hook) → Gherkin-to-Test → (hook) → Run-Prompt →
  [For each prompt: test-creator → coder → standards → tester]
```

## Execution Steps

### 1. **Initialization Phase** (Context & Exploration)

Invoke `init-explorer` agent to:
1. Explore the target project structure
2. Read/create progress file (`claude-progress.txt`)
3. Read/create feature list (`feature_list.md`) with comprehensive feature requirements
4. Invoke the `architect` agent automatically

```text
Task(subagent_type="init-explorer", prompt="
Explore this project and initialize context for the architect workflow.

next_agent: architect
task: $ARGUMENTS

After exploration:
1. Create .feature_list.md.example if feature_list.md doesn't exist
2. Update claude-progress.txt with session start
3. Invoke the architect agent with the task
")
```

Wait for init-explorer to complete (it will invoke architect internally).

### 2. **BDD Phase** (Behavior-Driven Scenarios)
Invoke `bdd-agent` with:
```text
Based on the feature request: $ARGUMENTS
And the DRAFT spec in: specs/DRAFT-*.md

Generate comprehensive Gherkin scenarios that capture the expected behavior.
Present ALL scenarios to the user for confirmation before proceeding.

Save confirmed scenarios to: ./tests/bdd/*.feature
Create BDD spec summary: specs/BDD-SPEC-[feature-name].md
```

Wait for bdd-agent to complete.

**HOOK SIGNAL**: After bdd-agent completes, you will see a system message:
> "BDD Agent completed. Scope-Manager will be invoked automatically."

### 3. **Scope Validation Phase** (Complexity Guardrail)

Invoke `scope-manager` with:
```text
Analyze the generated BDD feature files in ./tests/bdd/
Determine if the scope is safe for implementation.
```

**Branching Logic based on Scope-Manager Result**:

#### **PATH A: FAIL (Too Complex)**
If Scope Manager returns `RESULT: FAIL` and `TARGET_TASK: [Name]`:

1.  **Do NOT** proceed to Gherkin-to-Test.
2.  **Loop Back** to the **Architect** agent with this precise instruction:
    ```text
    The previous design failed scope check. Break task '[TARGET_TASK]' down in `architects_digest.md` into smaller sub-components.
    Once decomposed, immediately pick the first sub-task and create a new DRAFT spec for it.
    ```
3.  **Restart** the process from the BDD Phase for this new sub-task.

#### **PATH B: TRIVIAL (Too Small)**
If Scope Manager returns `RESULT: TRIVIAL`:

1.  **Bypass** the QA, Gherkin, and Run-Prompt phases.
2.  Invoke `strict-coder` directly:
    ```text
    Task(subagent_type="strict-coder", prompt="
    Implement this trivial task directly:
    $ARGUMENTS

    Context: This was identified as a trivial change (config/text/simple fix).
    Reference: specs/DRAFT-*.md (if useful)
    ")
    ```
3.  Wait for strict-coder to complete.
4.  Proceed to **Completion & Continuation**.

#### **PATH C: PASS (Safe)**
If Scope Manager returns `RESULT: PASS`:
Proceed to the Requirements QA phase.

### 4. **Requirements QA Phase** (Semantic Guardrail)

Invoke `requirements-qa` with:
```text
Analyze the BDD feature files against the original User Prompt ($ARGUMENTS).
Validate that all requirements are covered and no hallucinations exist.
```

**Branching Logic based on QA Result**:

#### **PATH A: FAIL (Missed/Wrong Requirements)**
If Requirements QA returns `Status: FAIL`:

1.  **Do NOT** proceed.
2.  **Loop Back** to the **Architect** agent with the `specs/QA-REQUIREMENTS-REPORT.md` content.
3.  Instruction: *"The BDD features do not meet user requirements. Revise the spec and scenarios."*
4.  **Restart** from the BDD Phase.

#### **PATH B: PASS (Approved)**
If Requirements QA returns `Status: PASS`:
Proceed to the Gherkin-to-Test phase.

### 5. **Gherkin-to-Test Phase** (Convert BDD to Prompts)
When QA approves, invoke `gherkin-to-test` with:
```text
Convert the confirmed BDD scenarios to prompt files:

1. Read feature files from: ./tests/bdd/*.feature
2. Read BDD spec from: specs/BDD-SPEC-*.md
3. Invoke codebase-analyst to find reuse opportunities
4. Invoke refactor-decision-engine for "GO" signal
5. Create prompt files in: ./prompts/NNN-bdd-*.md
6. Report the prompt numbers for run-prompt

Use executor: bdd in frontmatter for all prompts.
```

Wait for gherkin-to-test to complete.

**HOOK SIGNAL**: After gherkin-to-test completes, you will see a system message:
> "Gherkin-to-test agent completed. Run-prompt will be invoked automatically by the orchestrator with: run-prompt [numbers] --sequential"

### 6. **Run-Prompt Phase** (TDD Implementation)
When you see the gherkin-to-test completion signal, invoke `run-prompt` command with the prompt numbers provided in the signal.

Example: If signal says "run-prompt 006 007 008 --sequential", execute:
```text
Execute prompts sequentially: [prompt-numbers] --sequential

For each prompt, the TDD flow will execute:
- test-creator: Write tests from Gherkin scenarios
- coder: Implement code to pass tests
- coding-standards-checker: Verify code quality (via hook)
- tester: Validate functionality (via hook)
```

Wait for all prompts to complete.

### 6. **Completion & Continuation**

**CRITICAL CHECK**: Before finishing, verify if this was part of a decomposed task list (e.g., in `architects_digest.md`).

**IF Pending Sub-Tasks Exist:**
1.  **Do NOT** stop or ask for confirmation.
2.  Emit a brief status: "Phase Complete. Automatically starting next phase: [Next Task Name]..."
3.  **Loop Back** to **Step 1 (Initialization)** or **Step 2 (BDD Phase)** to begin the next task immediately.

**IF All Tasks Complete:**
Provide the final summary:

```markdown
**BDD-TDD Pipeline Complete**

**Feature**: $ARGUMENTS

**Phases Completed**:
1. Init-Explorer: Project context gathered, feature list created
2. Architect: specs/DRAFT-*.md created
3. BDD: [N] scenarios confirmed by user
4. Scope-Manager: Validated feature complexity
5. Gherkin-to-Test: [M] prompt files created
6. Run-Prompt: All prompts executed

**Artifacts Created**:
- claude-progress.txt (updated)
- feature_list.md (if exists, updated)
- specs/DRAFT-[feature].md
- specs/BDD-SPEC-[feature].md
- specs/GAP-ANALYSIS.md
- ./tests/bdd/*.feature
- ./prompts/NNN-bdd-*.md (archived to completed/)

**Implementation**:
- Tests created: [count]
- Code implemented: [files]
- Standards: Passed
- Tests: Passed
- Features completed: X/Y

**Feature Ready**: Yes
```

## Signal-Response Pattern

This pipeline uses **signal-based orchestration**:

1. You invoke an agent
2. Agent completes its work
3. SubagentStop hook emits a system message signal
4. You see the signal in the conversation
5. You invoke the next agent based on the signal

**CRITICAL**: Do not proceed to the next phase until you see the hook signal confirming the previous phase completed.

## Error Handling

If any phase fails or encounters issues:
- The agent will invoke the `stuck` agent
- The stuck agent will get human guidance
- Follow the guidance to resolve the issue
- Resume the pipeline from the failed step

## Quality Gates

Quality gates are automatically triggered via hooks:
- After `coder` completes → `coding-standards-checker` signal
- After `coding-standards-checker` completes → `tester` signal

These happen automatically within the run-prompt execution.

## Feature List Protocol

The `feature_list.md` file prevents one-shotting and premature victory:
- Features are broken into granular, testable units
- Each feature has `[ ] Incomplete` status initially
- Agents work on ONE feature at a time
- Only mark `[x] Complete` after verified testing

## Notes

- **BDD Scenarios are Sequential**: Always use `--sequential` flag for BDD prompts
- **User Confirmation Required**: BDD-agent will not proceed without user approval
- **Retry Limit**: BDD-agent has 5 retry attempts for clarifications
- **Codebase Analysis**: gherkin-to-test invokes codebase-analyst internally
- **Refactoring**: refactor-decision-engine runs before prompt creation
- **Progress Tracking**: claude-progress.txt maintains session history across context windows
