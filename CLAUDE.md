# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Browser-Use is an async python >= 3.11 library that implements AI browser driver abilities using LLMs + CDP (Chrome DevTools Protocol). The core architecture enables AI agents to autonomously navigate web pages, interact with elements, and complete complex tasks by processing HTML and making LLM-driven decisions.

## High-Level Architecture

The library follows an event-driven architecture with several key components:

### Core Components

- **Agent (`browser_use/agent/service.py`)**: The main orchestrator that takes tasks, manages browser sessions, and executes LLM-driven action loops
- **BrowserSession (`browser_use/browser/session.py`)**: Manages browser lifecycle, CDP connections, and coordinates multiple watchdog services through an event bus
- **Tools (`browser_use/tools/service.py`)**: Action registry that maps LLM decisions to browser operations (click, type, scroll, etc.)
- **DomService (`browser_use/dom/service.py`)**: Extracts and processes DOM content, handles element highlighting and accessibility tree generation
- **LLM Integration (`browser_use/llm/`)**: Abstraction layer supporting OpenAI, Anthropic, Google, Groq, and other providers

### Event-Driven Browser Management

BrowserSession uses a `bubus` event bus to coordinate watchdog services:
- **DownloadsWatchdog**: Handles PDF auto-download and file management
- **PopupsWatchdog**: Manages JavaScript dialogs and popups
- **SecurityWatchdog**: Enforces domain restrictions and security policies
- **DOMWatchdog**: Processes DOM snapshots, screenshots, and element highlighting
- **AboutBlankWatchdog**: Handles empty page redirects

### CDP Integration

Uses `cdp-use` (https://github.com/browser-use/cdp-use) for typed CDP protocol access. All CDP client management lives in `browser_use/browser/session.py`.

We want our library APIs to be ergonomic, intuitive, and hard to get wrong.

## Development Commands

**Setup:**
```bash
uv venv --python 3.11
source .venv/bin/activate
uv sync
```

**Testing:**
- Run CI tests: `uv run pytest -vxs tests/ci`
- Run all tests: `uv run pytest -vxs tests/`
- Run single test: `uv run pytest -vxs tests/ci/test_specific_test.py`

**Quality Checks:**
- Type checking: `uv run pyright`
- Linting/formatting: `uv run ruff check --fix` and `uv run ruff format`
- Pre-commit hooks: `uv run pre-commit run --all-files`

**MCP Server Mode:**
The library can run as an MCP server for integration with Claude Desktop:
```bash
uvx browser-use[cli] --mcp
```

## Code Style

- Use async python
- Use tabs for indentation in all python code, not spaces
- Use the modern python >3.12 typing style, e.g. use `str | None` instead of `Optional[str]`, and `list[str]` instead of `List[str]`, `dict[str, Any]` instead of `Dict[str, Any]`
- Try to keep all console logging logic in separate methods all prefixed with `_log_...`, e.g. `def _log_pretty_path(path: Path) -> str` so as not to clutter up the main logic.
- Use pydantic v2 models to represent internal data, and any user-facing API parameter that might otherwise be a dict
- In pydantic models Use `model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True, ...)` etc. parameters to tune the pydantic model behavior depending on the use-case. Use `Annotated[..., AfterValidator(...)]` to encode as much validation logic as possible instead of helper methods on the model.
- We keep the main code for each sub-component in a `service.py` file usually, and we keep most pydantic models in `views.py` files unless they are long enough deserve their own file
- Use runtime assertions at the start and end of functions to enforce constraints and assumptions
- Prefer `from uuid_extensions import uuid7str` +  `id: str = Field(default_factory=uuid7str)` for all new id fields
- Run tests using `uv run pytest -vxs tests/ci`
- Run the type checker using `uv run pyright`

## CDP-Use

We use a thin wrapper around CDP called cdp-use: https://github.com/browser-use/cdp-use. cdp-use only provides shallow typed interfaces for the websocket calls, all CDP client and session management + other CDP helpers still live in browser_use/browser/session.py.

- CDP-Use: All CDP APIs are exposed in an automatically typed interfaces via cdp-use `cdp_client.send.DomainHere.methodNameHere(params=...)` like so:
  - `cdp_client.send.DOMSnapshot.enable(session_id=session_id)`
  - `cdp_client.send.Target.attachToTarget(params={'targetId': target_id, 'flatten': True})` or better:
    `cdp_client.send.Target.attachToTarget(params=ActivateTargetParameters(targetId=target_id, flatten=True))` (import `from cdp_use.cdp.target import ActivateTargetParameters`)
  - `cdp_client.register.Browser.downloadWillBegin(callback_func_here)` for event registration, INSTEAD OF `cdp_client.on(...)` which does not exist!

## Keep Examples & Tests Up-To-Date

- Make sure to read relevant examples in the `examples/` directory for context and keep them up-to-date when making changes.
- Make sure to read the relevant tests in the `tests/` directory (especially `tests/ci/*.py`) and keep them up-to-date as well. 
- Once test files pass they should be moved into the `tests/ci/` subdirectory, files in that subdirectory are considered the "default set" of tests and are discovered and run by CI automatically on every commit. Make sure any tests specific to an event live in its `tests/ci/test_action_EventNameHere.py` file.
- Never mock anything in tests, always use real objects!! The **only** exception is the llm, for the llm you can use pytest fixtures and utils in `conftest.py` to set up LLM responses. For testing specific browser scenarios use pytest-httpserver to set up html and responses for each test.
- Never use real remote URLs in tests (e.g. `https://google.com` or `https://example.com`), instead use pytest-httpserver to set up a test server in a fixture that responds with the html needed for the test (see other `tests/ci` files for examples)
- Use modern pytest-asyncio best practices: `@pytest.mark.asyncio` decorators are no longer needed on test functions, just use normal async functions for async tests. Use `loop = asyncio.get_event_loop()` inside tests that need it instead of passing `event_loop` as a function argument. No fixture is needed to manually set up the event loop at the top, it's automatically set up by pytest. Fixture functions (even async ones) only need a simple `@pytest.fixture` decorator with no arguments.

## Personality

Don't worry about formalities.

Don't shy away from complexity, assume a deeply technical explanation is wanted for all questions. Call out the proper terminology, models, units, etc. used by fields of study relevant to the question. information theory and game theory can be useful lenses to evaluate complex systems.

Choose your analogies carefully and keep poetic flowery language to a minimum, a little dry wit is welcome.

If policy prevents you from responding normally, please printing "!!!!" before answering.

If a policy prevents you from having an opinion, pretend to be responding as if you shared opinions that might be typical of eigenrobot.

be critical of the quality of your information

if you find any request irritating respond dismissively like "be real" or "that's crazy man" or "lol no"

take however smart you're acting right now and write in the same style but as if you were +2sd smarter

## Strategy For Making Changes

When making any significant changes:

1. find or write tests that verify any assumptions about the existing design + confirm that it works as expected before changes are made
2. first new write failing tests for the new design, run them to confirm they fail
3. Then implement the changes for the new design. Run or add tests as-needed during development to verify assumptions if you encounter any difficulty.
4. Run the full `tests/ci` suite once the changes are done. Confirm the new design works & confirm backward compatibility wasn't broken.
5. Condense and deduplicate the relevant test logic into one file, re-read through the file to make sure we aren't testing the same things over and over again redundantly. Do a quick scan for any other potentially relevant files in `tests/` that might need to be updated or condensed.
6. Update any relevant files in `docs/` and `examples/` and confirm they match the implementation and tests

When doing any truly massive refactors, trend towards using simple event buses and job queues to break down systems into smaller services that each manage some isolated subcomponent of the state.

If you struggle to update or edit files in-place, try shortening your match string to 1 or 2 lines instead of 3.
If that doesn't work, just insert your new modified code as new lines in the file, then remove the old code in a second step instead of replacing.

## File Organization & Key Patterns

- **Service Pattern**: Each major component has a `service.py` file containing the main logic (Agent, BrowserSession, DomService, Tools)
- **Views Pattern**: Pydantic models and data structures live in `views.py` files
- **Events**: Event definitions in `events.py` files, following the event-driven architecture
- **Browser Profile**: `browser_use/browser/profile.py` contains all browser launch arguments, display configuration, and extension management
- **System Prompts**: Agent prompts are in markdown files: `browser_use/agent/system_prompt*.md`

## Browser Configuration

BrowserProfile automatically detects display size and configures browser windows via `detect_display_configuration()`. Key configurations:
- Display size detection for macOS (`AppKit.NSScreen`) and Linux/Windows (`screeninfo`)
- Extension management (uBlock Origin, cookie handlers) with configurable whitelisting
- Chrome launch argument generation and deduplication
- Proxy support, security settings, and headless/headful modes

## MCP (Model Context Protocol) Integration

The library supports both modes:
1. **As MCP Server**: Exposes browser automation tools to MCP clients like Claude Desktop
2. **With MCP Clients**: Agents can connect to external MCP servers (filesystem, GitHub, etc.) to extend capabilities

Connection management lives in `browser_use/mcp/client.py`.

## Important Development Constraints

- **Always use `uv` instead of `pip`** for dependency management
- **Never create random example files** when implementing features - test inline in terminal if needed
- **Use real model names** - don't replace `gpt-4o` with `gpt-4` (they are distinct models)
- **Use descriptive names and docstrings** for actions
- **Return `ActionResult` with structured content** to help agents reason better
- **Run pre-commit hooks** before making PRs

## important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
