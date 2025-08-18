

# Browser-Use Repository Overview

## Purpose
Browser-use is an open-source library that enables AI agents to control web browsers for automation tasks. It provides a bridge between large language models (LLMs) and browser automation capabilities, allowing agents to perform tasks like web scraping, form filling, and interactive browsing.

## General Setup
- **Programming Language**: Python 3.11+
- **Dependencies**: Uses Playwright for browser automation, various LLM APIs (OpenAI, Anthropic, etc.), and other utilities
- **Installation**: `pip install browser-use`
- **Browser Requirement**: Playwright Chromium (`playwright install chromium --with-deps --no-shell`)
- **Configuration**: Requires API keys for LLM providers in `.env` file

## Repository Structure
```
browser-use/
├── .github/                  # GitHub workflows and templates
│   ├── workflows/            # CI/CD pipelines (lint.yml, test.yaml, etc.)
├── .openhands/               # OpenHands configuration
│   └── microagents/
│       └── repo.md           # This file
├── browser_use/              # Main source code
│   ├── agent/                # Agent-related modules
│   ├── browser/              # Browser automation components
│   ├── controller/           # Controller logic
│   ├── dom/                  # DOM manipulation tools
│   ├── llm/                  # Language model integrations
│   └── ...                   # Other modules
├── examples/                 # Example scripts and use cases
├── tests/                    # Test suites and agent tasks
│   ├── agent_tasks/          # YAML files for agent task testing
│   └── ci/                   # Continuous integration tests
├── docs/                     # Documentation files
├── bin/                      # Scripts and utilities
├── Dockerfile                # Docker configuration
├── pyproject.toml           # Project metadata and dependencies
├── README.md                # Main documentation
└── ...                       # Other configuration files
```

## CI/CD Pipelines

### Linting Workflow (`lint.yml`)
- **Triggers**: Push to main/stable/release branches, PRs, tags
- **Jobs**:
  - `lint-syntax`: Checks for syntax errors using Ruff
  - `lint-style`: Enforces code style with pre-commit hooks (Ruff, pyupgrade, etc.)
  - `lint-typecheck`: Type checking with Pyright

### Testing Workflow (`test.yaml`)
- **Triggers**: Same as linting
- **Jobs**:
  - `find_tests`: Discovers test files in `tests/ci/` directory
  - `tests`: Runs individual test files in parallel with Playwright setup
  - `evaluate-tasks`: Evaluates agent tasks and reports results

### Pre-commit Configuration
- **Hooks**:
  - `ruff`: Code linting and formatting
  - `pyupgrade`: Python version upgrades
  - `codespell`: Spelling checks
  - `pyright`: Type checking
  - Various file format and content checks

## Key Features
- **LLM Integration**: Supports multiple LLM providers (OpenAI, Anthropic, etc.)
- **Browser Automation**: Leverages Playwright for reliable browser control
- **MCP Support**: Model Context Protocol integration for external tool connections
- **Extensible**: Modular architecture allows for custom extensions and plugins
- **Cloud Version**: Hosted version available for instant browser automation

## Getting Started
1. Install the package: `pip install browser-use`
2. Install Playwright: `playwright install chromium --with-deps --no-shell`
3. Add API keys to `.env` file
4. Create an agent with a task and LLM model
5. Run the agent: `await agent.run()`

## Examples
- Shopping automation (add items to cart)
- Web scraping and data extraction
- Form filling and submission
- Interactive browsing tasks

## Roadmap
- Improve agent memory for longer task sequences
- Enhance planning capabilities
- Reduce token consumption
- Add support for more UI elements and states

## Contributing
- Follow the contributing guidelines in `CONTRIBUTING.md`
- Add tests for new features
- Maintain code quality with pre-commit hooks and CI checks

