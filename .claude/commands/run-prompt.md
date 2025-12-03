---
name: run-prompt
description: Delegate one or more prompts to fresh sub-task contexts with parallel or sequential execution
argument-hint: <prompt-number(s)-or-name> [--parallel|--sequential]
---

<objective>
Execute one or more prompts from `./prompts/` as delegated sub-tasks with fresh context. Follows Test-Driven Development (TDD) approach by routing code tasks through: test-creator → coder → coding-standards-checker → tester. Non-code tasks route directly to general-purpose agents. Supports single prompt execution, parallel execution of multiple independent prompts, and sequential execution of dependent prompts.
</objective>

<input>
The user will specify which prompt(s) to run via $ARGUMENTS, which can be:

**Single prompt:**

- Empty (no arguments): Run the most recently created prompt (default behavior)
- A prompt number (e.g., "001", "5", "42")
- A partial filename (e.g., "user-auth", "dashboard")

**Multiple prompts:**

- Multiple numbers (e.g., "005 006 007")
- With execution flag: "005 006 007 --parallel" or "005 006 007 --sequential"
- If no flag specified with multiple prompts, default to --sequential for safety
  </input>

<process>
<step1_parse_arguments>
Parse $ARGUMENTS to extract:
- Prompt numbers/names (all arguments that are not flags)
- Execution strategy flag (--parallel or --sequential)

<examples>
- "005" → Single prompt: 005
- "005 006 007" → Multiple prompts: [005, 006, 007], strategy: sequential (default)
- "005 006 007 --parallel" → Multiple prompts: [005, 006, 007], strategy: parallel
- "005 006 007 --sequential" → Multiple prompts: [005, 006, 007], strategy: sequential
</examples>
</step1_parse_arguments>

<step2_resolve_files>
For each prompt number/name:

- If empty or "last": Find with `!ls -t ./prompts/*.md | head -1`
- If a number: Find file matching that zero-padded number (e.g., "5" matches "005-_.md", "42" matches "042-_.md")
- If text: Find files containing that string in the filename

<matching_rules>

- If exactly one match found: Use that file
- If multiple matches found: List them and ask user to choose
- If no matches found: Report error and list available prompts
  </matching_rules>
  </step2_resolve_files>

<step2b_analyze_task_type>
For each resolved prompt file, determine the task type to choose the appropriate executor:

<frontmatter_detection>
Check if prompt has YAML frontmatter with executor specification:

```yaml
---
executor: tdd | coder | general-purpose | bdd
---
```

Executor options:
- **tdd**: Test-Driven Development flow (test-creator → coder → standards → tester)
- **coder**: Direct implementation flow (coder → standards → tester)
- **general-purpose**: Non-code tasks (research, documentation, analysis)
- **bdd**: BDD-driven TDD flow with Gherkin context (test-creator → coder → standards → tester). Same as TDD but prompts include Gherkin scenarios that guide test creation.

If frontmatter specifies executor explicitly, use that (skip auto-detection).
</frontmatter_detection>

<auto_detection>
If no frontmatter or no executor specified, analyze prompt content for task type indicators:

<code_task_indicators>
Count occurrences of code implementation keywords:
- Implementation verbs: "implement", "build", "create", "add feature", "develop", "code"
- Code modification: "modify", "edit", "update", "refactor", "fix bug"
- File operations: mentions of code files (.js, .ts, .py, .go, .java, .tsx, .jsx, etc.)
- Component/class creation: "component", "class", "function", "module", "API", "endpoint"
- Testing requirements: "test", "ensure tests pass", "add tests", "unit test"
- Code quality: "coding standards", "code conventions", "follow standards"
- Technical stack mentions: "React", "Node", "Django", "Go", "TypeScript", etc.
- Code structure tags: `<implementation>`, `<requirements>`, `<verification>` with code context

**Scoring**: Each indicator found = +1 point
</code_task_indicators>

<non_code_indicators>
Count occurrences of non-code task keywords:
- Research verbs: "research", "investigate", "explore", "analyze", "study"
- Documentation: "document", "write documentation", "create guide", "write README"
- Analysis: "analyze", "review", "assess", "evaluate", "compare"
- Data tasks: "gather data", "collect information", "compile", "summarize"
- Report generation: "create report", "generate summary", "write analysis"

**Scoring**: Each indicator found = +1 point
</non_code_indicators>

<decision_logic>
- If code_score >= 3: **Code task (TDD)** → Use TDD workflow (test-creator → coder)
- If non_code_score > code_score AND code_score < 3: **Non-code task** → Use general-purpose
- If code_score >= 2 AND mentions tests/standards: **Code task (TDD)** → Use TDD workflow
- Default (ambiguous): **Code task (TDD)** → Use TDD workflow (safer default for quality)

**Rationale**: When in doubt, route through TDD to ensure tests are written first. This provides better quality gates and clearer specifications for implementation.
</decision_logic>
</auto_detection>

<task_type_output>
Store for each prompt:
- file_path: "./prompts/XXX-name.md"
- executor: "tdd" | "coder" | "general-purpose" | "bdd"
- detection_method: "frontmatter" | "auto-detected" | "default"
</task_type_output>
</step2b_analyze_task_type>

<step3_execute>
<single_prompt>

1. Read the complete contents of the prompt file
2. Analyze task type (step2b) to determine executor
3. Route based on executor type:

   <tdd_task_routing>
   If executor == "tdd" OR executor == "bdd":
   - **Step 1**: Invoke Task tool with subagent_type="test-creator" and prompt content
   - **Test-creator agent** creates comprehensive failing tests following TDD Red phase
   - For BDD prompts: test-creator uses the Gherkin scenarios in `<gherkin>` tags as specification
   - Wait for test-creator to complete and return test files
   - **Step 2**: Invoke Task tool with subagent_type="coder" with BOTH:
     * Original prompt content
     * Test files created by test-creator
     * Instruction: "Implement code to make these tests pass"
   - **Coder agent** implements the task to pass the tests (TDD Green phase)
   - Wait for coder to complete
   - **Step 3**: SubagentStop hook signals → invoke coding-standards-checker
   - Wait for standards check to complete
   - **Step 4**: SubagentStop hook signals → invoke tester
   - Full TDD cycle: Red (tests) → Green (implementation) → Quality gates
   </tdd_task_routing>

   <code_task_routing>
   If executor == "coder":
   - Invoke Task tool with subagent_type="coder" and prompt content
   - **Coder agent** implements the task directly (no test-creator phase)
   - Wait for coder to complete
   - SubagentStop hook signals → invoke coding-standards-checker
   - SubagentStop hook signals → invoke tester
   - Direct implementation workflow (skip TDD test-first approach)
   </code_task_routing>

   <general_task_routing>
   If executor == "general-purpose":
   - Invoke Task tool with subagent_type="general-purpose"
   - Delegate prompt content as-is
   - No quality gate hooks triggered
   - Wait for completion
   </general_task_routing>

4. Archive prompt to `./prompts/completed/` with metadata (include executor type used)
5. Return results with execution summary
   </single_prompt>

<parallel_execution>

1. Read all prompt files
2. Analyze task type for each prompt (step2b) to determine executors
3. **Execute all prompts in PARALLEL in a SINGLE MESSAGE**:

   <mixed_executor_parallel>
   For each prompt, route based on its executor:

   - TDD/BDD tasks: Invoke Task tool with subagent_type="test-creator" (tests created first, then coder invoked sequentially)
   - Code tasks: Invoke Task tool with subagent_type="coder" (direct implementation)
   - General tasks: Invoke Task tool with subagent_type="general-purpose"

   **IMPORTANT**: TDD tasks CANNOT be parallelized internally (test-creator must finish before coder). However, multiple TDD tasks can start in parallel, each running their own test-creator → coder sequence.

   **CRITICAL**: All initial tool invocations (Task tools) MUST be in a single message for true parallel execution.

   <example>
   Single message with multiple tool calls:
   - Task tool with subagent_type="test-creator" for prompt 005 (TDD task)
   - Task tool with subagent_type="general-purpose" for prompt 006 (research task)
   - Task tool with subagent_type="coder" for prompt 007 (direct code task)

   All execute simultaneously!
   </example>
   </mixed_executor_parallel>

   <important_note>
   - TDD tasks: test-creator → coder → standards → tester (sequential within each task)
   - Code tasks: coder → standards → tester (sequential within each task)
   - General tasks: complete without quality gates
   - Multiple tasks can execute in parallel, but each task's internal flow is sequential
   - Each coder invocation triggers SubagentStop hooks for quality gates
   </important_note>

4. Wait for ALL to complete
5. Archive all prompts with metadata (include executor type for each)
6. Return consolidated results with execution summary per prompt
   </parallel_execution>

<sequential_execution>

1. Read first prompt file
2. Analyze task type (step2b) to determine executor
3. Route based on executor:
   - If "tdd" or "bdd": Invoke Task tool with subagent_type="test-creator" → wait for tests → invoke Task tool with subagent_type="coder" → wait for implementation → wait for quality gates (standards → tester via hooks)
   - If "coder": Invoke Task tool with subagent_type="coder" → wait for implementation → wait for quality gates (standards → tester via hooks)
   - If "general-purpose": Invoke Task tool with subagent_type="general-purpose" → wait for completion
4. Archive first prompt with metadata
5. Read second prompt file
6. Analyze task type for second prompt
7. Route based on executor (same as step 3)
8. Wait for completion
9. Archive second prompt
10. Repeat for remaining prompts in sequence
11. Return consolidated results with execution summary per prompt

<sequential_benefits>
- Each prompt completes fully (including quality gates for code tasks) before next starts
- Dependencies between prompts are respected
- Clear progression through workflow
- Easier debugging if one prompt fails
</sequential_benefits>
    </sequential_execution>
    </step3_execute>
    </process>

<context_strategy>
By delegating to a sub-task, the actual implementation work happens in fresh context while the main conversation stays lean for orchestration and iteration.
</context_strategy>

<output>
<single_prompt_output>
✓ Executed: ./prompts/005-implement-feature.md
✓ Executor: tdd (auto-detected)
✓ TDD Flow: test-creator ✓ → coder ✓ → standards ✓ → tester ✓
✓ Archived to: ./prompts/completed/005-implement-feature.md

<results>
[Summary of what the sub-task accomplished, including tests created and implementation]
</results>
</single_prompt_output>

<parallel_output>
✓ Executed in PARALLEL:

- ./prompts/005-implement-auth.md (executor: tdd, TDD flow completed)
- ./prompts/006-research-competitors.md (executor: general-purpose)
- ./prompts/007-implement-ui.md (executor: coder, direct implementation flow)

✓ All archived to ./prompts/completed/

<results>
Prompt 005 (tdd): [Tests created → Implementation summary with quality gate results]
Prompt 006 (general-purpose): [Research summary]
Prompt 007 (coder): [Implementation summary with quality gate results]
</results>
</parallel_output>

<sequential_output>
✓ Executed SEQUENTIALLY:

1. ./prompts/005-setup-database.md → Success (executor: tdd, TDD flow ✓)
2. ./prompts/006-create-migrations.md → Success (executor: coder, quality gates ✓)
3. ./prompts/007-seed-data.md → Success (executor: tdd, TDD flow ✓)

✓ All archived to ./prompts/completed/

<results>
[Consolidated summary showing progression through each step with TDD flows and quality gate results]
</results>
</sequential_output>
</output>

<critical_notes>

<execution_rules>
- For parallel execution: ALL initial tool calls (Task tools) MUST be in a single message
- For sequential execution: Wait for each prompt to complete fully (including TDD flow and quality gates) before starting next
- TDD flow is sequential within each task: test-creator → coder → standards → tester
- Archive prompts only after successful completion
- If any prompt fails, stop sequential execution and report error
- Provide clear, consolidated results for multiple prompt execution
</execution_rules>

<routing_rules>
- ALWAYS analyze task type before execution (frontmatter check → auto-detection)
- Code tasks (default) → TDD workflow: test-creator → coder → standards → tester
- Direct code tasks → coder workflow: coder → standards → tester (skip test-creator)
- Non-code tasks → general-purpose agent (no hooks)
- When in doubt → route to TDD workflow (safer default for quality)
- Respect explicit frontmatter executor specifications
</routing_rules>

<quality_gate_behavior>
- **TDD Flow**: test-creator creates tests → coder implements → SubagentStop hooks trigger standards → tester
- **Direct Code Flow**: coder implements → SubagentStop hooks trigger standards → tester
- **General Flow**: general-purpose agent executes → no quality gates
- SubagentStop hooks automatically signal when to invoke coding-standards-checker
- Then hooks signal when to invoke tester
- This happens automatically for ALL code tasks (both TDD and direct)
- General-purpose tasks skip quality gates entirely
- Mixed parallel execution: Code tasks get full workflows, general tasks don't
</quality_gate_behavior>

<frontmatter_usage>
To explicitly control executor, add to top of prompt file:

```yaml
---
executor: tdd
---
```
(Full TDD: test-creator → coder → standards → tester)

or

```yaml
---
executor: bdd
source_feature: ./tests/bdd/feature-name.feature
---
```
(BDD-driven TDD: Same as TDD but with Gherkin scenarios in `<gherkin>` tags guiding test creation. Used by gherkin-to-test agent for BDD pipeline.)

or

```yaml
---
executor: coder
---
```
(Direct implementation: coder → standards → tester, skip test-creator)

or

```yaml
---
executor: general-purpose
---
```
(Research/docs: no quality gates)

This overrides auto-detection.
</frontmatter_usage>
  </critical_notes>

<benefits>

<intelligent_routing>
✅ **Test-Driven Development**: Code tasks default to TDD workflow (tests written first)
✅ **Automatic Quality Gates**: All code tasks get standards checks and tests
✅ **Lightweight Non-Code Tasks**: Research, documentation, analysis tasks skip unnecessary quality gates
✅ **Flexible Control**: Frontmatter allows explicit executor control when needed
✅ **Smart Defaults**: Auto-detection means prompts "just work" without manual configuration
✅ **CI/CD Ready**: Autonomous execution with appropriate quality gates per task type
</intelligent_routing>

<workflow_integration>
✅ **TDD First Approach**: Tests are created before implementation, providing clear specifications
✅ **Leverages Agent Infrastructure**: Reuses existing hooks, agents, and quality gate workflows
✅ **Consistent Quality**: Code changes always go through the same rigorous process
✅ **Hook-Driven**: SubagentStop hooks automatically coordinate quality gates
✅ **Clear Specification**: test-creator agent provides clear contract for coder agent to fulfill
✅ **Better Coverage**: Tests written first ensure comprehensive test coverage
</workflow_integration>

<examples>

<example_auto_detection_tdd>
Prompt content:
"Implement a React component for user authentication with JWT tokens. Ensure tests pass and code follows standards."

Auto-detection:
- Keywords found: "implement" (1), "component" (1), "React" (1), "authentication" (1), "tests" (1), "standards" (1)
- Code score: 6
- Decision: Route to TDD workflow ✓
- Execution flow:
  1. test-creator creates failing tests for authentication component
  2. coder implements component to pass tests
  3. coding-standards-checker verifies code quality
  4. tester validates functionality
- Quality gates applied: TDD ✓ | Standards ✓ | Tests ✓
</example_auto_detection_tdd>

<example_auto_detection_research>
Prompt content:
"Research competitor APIs and document their authentication approaches. Create a comparison report."

Auto-detection:
- Keywords found: "research" (1), "document" (1), "report" (1)
- Non-code score: 3, Code score: 0
- Decision: Route to general-purpose ✓
- Quality gates: None (not needed for research)
</example_auto_detection_research>

<example_frontmatter_override_direct>
Prompt with frontmatter:
```yaml
---
executor: coder
---

Quick fix: Update the login button color to match brand guidelines.
```

Execution:
- Frontmatter detected: executor = coder
- Auto-detection skipped (frontmatter takes precedence)
- Routed to: coder agent (direct implementation, skip test-creator) ✓
- Execution flow:
  1. coder implements the change
  2. coding-standards-checker verifies code quality
  3. tester validates functionality
- Quality gates: Standards ✓ | Tests ✓
- Note: TDD test-creator skipped for simple change
</example_frontmatter_override_direct>

<example_frontmatter_override_general>
Prompt with frontmatter:
```yaml
---
executor: general-purpose
---

Research the latest React 19 features and create a summary document.
```

Execution:
- Frontmatter detected: executor = general-purpose
- Auto-detection skipped (frontmatter takes precedence)
- Routed to: general-purpose agent ✓
- Quality gates: None (research task)
</example_frontmatter_override_general>

<example_bdd_execution>
Prompt with BDD frontmatter (created by gherkin-to-test agent):
```yaml
---
executor: bdd
source_feature: ./tests/bdd/user-authentication.feature
---

<objective>
Implement the User Authentication feature as defined by the BDD scenarios below.
</objective>

<gherkin>
Feature: User Authentication
  As a registered user
  I want to log in to my account
  So that I can access my personalized dashboard

  Scenario: Successful login with valid credentials
    Given a registered user with email "user@example.com"
    When the user logs in with correct password
    Then the user receives a valid JWT token
    And the user is redirected to dashboard

  Scenario: Failed login with invalid password
    Given a registered user with email "user@example.com"
    When the user logs in with incorrect password
    Then the user receives an authentication error
    And no JWT token is issued
</gherkin>

<requirements>
1. User authentication endpoint
2. JWT token generation
3. Error handling for invalid credentials
</requirements>
```

Execution:
- Frontmatter detected: executor = bdd
- Routed to: TDD workflow with Gherkin context
- Execution flow:
  1. test-creator reads Gherkin scenarios and creates tests that verify each scenario
  2. coder implements authentication to pass all tests
  3. coding-standards-checker verifies code quality
  4. tester validates all scenarios pass
- Quality gates: TDD ✓ | Standards ✓ | Tests ✓
- Note: BDD prompts always run sequentially (--sequential flag)
</example_bdd_execution>

</examples>

</benefits>