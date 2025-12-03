# Project Configuration

This project uses Claude Code with specialized agents and hooks for orchestrated development workflows.

## Available Commands

### `/architect` - BDD-TDD Development Workflow
Use this command to create implementation prompts following BDD and TDD best practices:
- Creates greenfield specification for the feature
- Generates Gherkin BDD scenarios
- Converts scenarios to TDD prompts
- Tests are written from Gherkin scenarios (Red phase)
- Implementation follows to make tests pass (Green phase)
- Full quality gates: standards checks and testing

**When to use**: For new features where you want comprehensive BDD test coverage.

**Example**: `/architect Build a user authentication system with JWT`

**Flow**: init-explorer → architect → bdd-agent → gherkin-to-test → codebase-analyst → refactor-decision → test-creator → coder → standards → tester → bdd-test-runner

### `/coder` - Orchestrated Development
Use this command when you want to implement features with full orchestration:
- Automatically breaks down tasks into to-do items
- Delegates implementation to specialized coder agents
- Enforces coding standards through automated checks
- Runs tests automatically after implementation
- Provides comprehensive quality gates

**When to use**: For implementing new features, building projects, or complex multi-step coding tasks where you want direct manual orchestration.

**Example**: `/coder Build a REST API with user authentication`

### `/run-prompt` - Execute Saved Prompts
Use this command to execute one or more prompts from `./prompts/` directory:
- Automatically detects task type (TDD, direct code, or research)
- Routes to appropriate workflow based on task type
- Supports parallel execution with `--parallel` flag
- Supports sequential execution with `--sequential` flag
- Can specify executor via frontmatter in prompt files

**When to use**: To execute prompts created by `/architect` or manually created prompts.

**Examples**:
- `/run-prompt 005` (execute prompt 005)
- `/run-prompt 005 006 007 --parallel` (execute three prompts in parallel)
- `/run-prompt 005 006 --sequential` (execute two prompts sequentially)

### `/refactor` - Code Refactoring
Use this command to refactor existing code to adhere to coding standards.

**When to use**: When you need to improve code quality without changing functionality.

**Example**: `/refactor src/components/UserForm.js`

### `/verifier` - Code Verification and Investigation
Use this command to investigate source code and verify claims, answer questions, or determine if queries are true/false.

**When to use**: When you need to verify a claim about the codebase, answer questions about code structure or functionality, or investigate specific code patterns.

**Example**: `/verifier Does the codebase have email validation?`

### `/fix-failing-tests` - Fix Failing Tests
Use this command to run the project's test suite and automatically fix any failures.

**When to use**: When tests are failing and you want to automatically attempt to fix them.

**Example**: `/fix-failing-tests`

### `/debugger` - CRASH-RCA Forensic Debugging
Use this command to start a forensic Root Cause Analysis debugging session:
- Enforces read-only investigation mode (Write/Edit tools blocked)
- Logs every investigation step with hypothesis and confidence
- Tracks evidence chain throughout investigation
- Generates structured RCA report on completion

**When to use**: When you need to systematically investigate a bug or issue with disciplined, evidence-based analysis.

**Example**: `/debugger Login API returns 500 errors intermittently`

**Flow**:
1. `init-explorer` gathers project context and progress
2. `crash.py start` initializes session (Forensic Mode ON)
3. `crash.py step` logs each hypothesis before investigation
4. Read-only tools gather evidence (Grep, Read, Glob, Bash)
5. `crash.py diagnose` generates RCA report (Forensic Mode OFF)

**Key Features**:
- **Forensic Mode**: Write/Edit blocked until diagnosis complete
- **Hypothesis Logging**: Every investigation step recorded
- **Evidence Chain**: All findings tracked with file:line references
- **Structured Report**: Standardized RCA output format

## Project Structure

- `.claude/agents/` - Specialized agent configurations
  - `init-explorer.md` - Initializer agent that explores codebase and sets up context
  - `architect.md` - Greenfield spec designer
  - `bdd-agent.md` - BDD specialist that generates Gherkin scenarios
  - `scope-manager.md` - Complexity gatekeeper for BDD features
  - `gherkin-to-test.md` - Converts Gherkin to TDD prompts
  - `codebase-analyst.md` - Finds reuse opportunities
  - `refactor-decision-engine.md` - Decides if refactoring needed
  - `test-creator.md` - TDD specialist that writes tests first
  - `coder.md` - Implementation specialist
  - `coding-standards-checker.md` - Code quality verifier
  - `tester.md` - Functionality verification
  - `bdd-test-runner.md` - Test infrastructure validator (Dockerfile.test, Makefile)
  - `refactorer.md` - Code refactoring specialist
  - `fix-failing-tests.md` - Fix failing tests specialist
  - `verifier.md` - Code investigation specialist
  - `stuck.md` - Human escalation agent
  - `debugger.md` - CRASH-RCA orchestrator for forensic debugging
  - `forensic.md` - Investigation specialist for CRASH sessions
  - `analyst.md` - RCA synthesis specialist
- `.claude/coding-standards/` - Code quality standards
- `.claude/commands/` - Custom slash commands
- `.claude/hooks/` - Automated workflow hooks
- `.claude/config.json` - Project configuration
- `tests/bdd/` - Gherkin feature files for BDD scenarios

## Hooks System

This project uses Claude Code hooks to automatically enforce quality gates:

### Configured Hooks

1. **post-init-explorer.sh** - Signals that project context is gathered
2. **post-bdd-agent.sh** - Signals gherkin-to-test after BDD scenarios generated
3. **post-gherkin-to-test.sh** - Signals run-prompt after prompts created
4. **post-coder-standards-check.sh** - Triggers coding standards check after coder completes
5. **post-standards-testing.sh** - Triggers testing after standards check passes
6. **post-tester-infrastructure.sh** - Triggers bdd-test-runner to validate test infrastructure
7. **crash-guardrail.py** - Blocks Write/Edit tools during CRASH debugging sessions

Hooks create state files in `.claude/.state/` to track workflow completion.

### Init-Explorer Agent

The `init-explorer` agent is the **initializer** that runs at the start of `/architect` and `/debugger` workflows. It:

1. **Orients to the project**: Runs `pwd`, `ls`, `git log`, `git status`
2. **Reads progress history**: Checks `claude-progress.txt` for previous session context
3. **Reads digest**: Checks `architects_digest.md` for task stack and recursive state
4. **Explores structure**: Uses the Explore agent to analyze tech stack and patterns
5. **Updates progress**: Logs this session's start to `claude-progress.txt`
6. **Invokes next agent**: Hands off to `architect` or `debugger` with full context

### Session Continuity Files

| File | Purpose |
|------|---------|
| `claude-progress.txt` | Session log showing what agents have done across context windows |
| `architects_digest.md` | Recursive task breakdown and architecture state |
| `feature_list.md` | Comprehensive feature requirements with completion status |
| `.feature_list.md.example` | Example template created if `feature_list.md` is missing |

### Feature List Protocol

The `feature_list.md` file prevents two common agent failure modes:
- **One-shotting**: Trying to implement everything at once
- **Premature victory**: Declaring the project done before all features work

**Rules for agents**:
1. Only modify the status checkbox - Never remove or edit feature descriptions
2. Mark `[x] Complete` only after verified testing - Not after implementation
3. Work on one feature at a time - Incremental progress
4. Read feature list at session start - Choose highest-priority incomplete feature

### CRASH-RCA Scripts

Located in `.claude/scripts/`:

- **crash.py** - State manager for forensic debugging sessions
  - `crash.py start "issue"` - Initialize session
  - `crash.py step --hypothesis "..." --action "..." --confidence 0.7` - Log investigation step
  - `crash.py status` - Check session state
  - `crash.py diagnose --root_cause "..." --justification "..." --evidence "..."` - Complete with RCA
  - `crash.py cancel` - Abort session

## Documentation Guidelines

- Place markdown documentation in `./docs/`
- Keep `README.md` in the root directory
- Ensure all header/footer links have actual pages (no 404s)

## Database Migration Rules (Flyway)

If the project already has a `./sql` folder, you cannot modify any of these existing files since these are used for Flyway migrations. Your only option if you need to make changes to the database schema is to add new `.sql` files.

## Workflow Comparison

### BDD-TDD Workflow (`/architect`)
**Best for**: New features with comprehensive test coverage, behavior-driven development

**Flow**:
1. `init-explorer` gathers project context, creates `architects_digest.md`
2. `architect` creates greenfield spec (or decomposes complex tasks)
3. `bdd-agent` generates Gherkin scenarios
4. `scope-manager` validates complexity (loops back to Architect if too complex)
5. `gherkin-to-test` invokes codebase-analyst and creates prompts
6. `run-prompt` executes prompts sequentially
7. For each prompt:
   - `test-creator` writes tests from Gherkin
   - `coder` implements to pass tests
   - `coding-standards-checker` verifies quality
   - `tester` validates functionality
   - `bdd-test-runner` validates test infrastructure (Dockerfile.test, Makefile, `make test`)

**Benefits**:
- Session continuity via `claude-progress.txt` and `feature_list.md`
- Prevents one-shotting and premature victory
- Tests derived from business-readable Gherkin scenarios
- Clear traceability from requirements to tests to code
- Full quality gates
- Living documentation via `.feature` files

### Direct Implementation (`/coder`)
**Best for**: Quick fixes, manual orchestration, iterative development

**Flow**:
1. Orchestrator breaks down task into todos
2. `coder` agent implements each todo
3. `coding-standards-checker` verifies code quality
4. `tester` validates functionality
5. Repeat for each todo item

**Benefits**:
- Manual control over task breakdown
- Direct implementation without test-first approach
- Iterative todo-based workflow

### Prompt Execution (`/run-prompt`)
**Best for**: Executing pre-created prompts, batch operations

**Flow**:
- Detects task type (TDD, BDD, direct code, or research)
- Routes to appropriate workflow
- Can execute multiple prompts in parallel or sequential
- Supports executor override via frontmatter (`tdd`, `bdd`, `coder`, `general-purpose`)

**Benefits**:
- Flexible execution strategies
- Batch processing
- Intelligent routing
- BDD prompts always run sequentially

## General Usage

For exploratory tasks, questions, or non-coding requests, you can interact with Claude Code normally without using specialized commands. Use:
- `/architect` for new features with TDD approach
- `/coder` for direct orchestrated implementation
- `/run-prompt` for executing saved prompts
- `/refactor` for code quality improvements
- `/fix-failing-tests` for fixing failing tests automatically
- `/verifier` for code investigation
- `/debugger` for forensic root cause analysis

### Forensic Debugging Workflow (`/debugger`)
**Best for**: Systematic bug investigation, intermittent issues, production incidents

**Flow**:
1. `init-explorer` gathers project context, reads progress and feature list
2. `/debugger "issue description"` starts CRASH-RCA session
3. Forensic Mode activates (Write/Edit blocked)
4. Log hypothesis with `crash.py step`
5. Investigate with read-only tools (Grep, Read, Glob)
6. Repeat steps 4-5 until confidence > 0.8
7. Complete with `crash.py diagnose`

**Benefits**:
- Session continuity via `claude-progress.txt`
- Prevents accidental code changes during investigation
- Forces disciplined hypothesis-driven debugging
- Creates audit trail of investigation steps
- Generates standardized RCA reports
