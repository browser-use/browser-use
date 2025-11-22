# Browser-Use: Complete Project Structure & Developer Guide

This document provides a comprehensive overview of the browser-use project structure, explaining what each file does and how you can modify and extend the functionality.

## Table of Contents

- [Project Overview](#project-overview)
- [Directory Structure](#directory-structure)
- [Core Components](#core-components)
- [Configuration Files](#configuration-files)
- [Extending the Library](#extending-the-library)
- [Examples & Tests](#examples--tests)

---

## Project Overview

**Browser-Use** is an AI-powered browser automation library that enables AI agents (LLMs) to control web browsers autonomously. It uses:
- **Playwright** for browser control
- **LangChain** for LLM integration
- **Pydantic** for data validation
- **Vision-based element detection** for intelligent DOM interaction

### Key Capabilities
- AI agents can perform complex web tasks (form filling, navigation, data extraction)
- Multi-step workflows with memory
- Support for multiple LLM providers (OpenAI, Anthropic, Google, DeepSeek, etc.)
- Extensible action system with custom functions
- Computer vision (screenshots with bounding boxes) to help LLMs understand page layout

---

## Directory Structure

```
browser-use/
├── browser_use/          # Main source code
│   ├── agent/           # AI agent logic and orchestration
│   ├── browser/         # Browser control layer (Playwright)
│   ├── controller/      # Action registry and execution
│   ├── dom/            # DOM processing and extraction
│   └── telemetry/      # Analytics
├── examples/           # 50+ usage examples
│   ├── browser/        # Browser-specific features
│   ├── use-cases/      # Real-world applications
│   ├── custom-functions/# Extending with custom actions
│   ├── features/       # Advanced features
│   ├── models/         # LLM provider examples
│   └── integrations/   # Third-party integrations
├── tests/              # Comprehensive test suite
├── docs/               # Documentation (Mintlify format)
├── eval/               # Model evaluation scripts
├── static/             # Logos and images
├── .github/            # GitHub workflows
└── [config files]      # pyproject.toml, Dockerfile, etc.
```

---

## Core Components

### 1. `browser_use/agent/` - AI Agent Orchestration

The heart of the AI decision-making system.

#### **`service.py`** (~1,400 lines)
**Purpose**: Main `Agent` class that orchestrates the entire automation process

**What it does**:
- Manages agent lifecycle and state
- Coordinates with LLM for decision making
- Executes actions via the Controller
- Handles memory and message management
- Supports hooks (before/after step callbacks)

**Key methods**:
```python
async def run(max_steps: int = 100) -> AgentHistoryList:
    # Main execution loop
    # 1. Extract DOM state
    # 2. Create context for LLM
    # 3. Get LLM decision
    # 4. Execute actions
    # 5. Record results
    # 6. Repeat until task done
```

**How to modify**:
- Change agent behavior by adjusting `AgentSettings`
- Add custom hooks for pre/post step processing
- Modify max steps, token limits, retry logic

#### **`views.py`** (~441 lines)
**Purpose**: Data models for agent configuration and state

**Key models**:
- `AgentSettings`: Configuration options
  - `max_failures`: How many errors before stopping
  - `max_input_tokens`: Token budget for LLM
  - `use_vision`: Enable/disable screenshot analysis
  - `save_conversation_path`: Debug conversation history
  - And more...

- `AgentState`: Runtime state
  - `n_steps`: Current step count
  - `history`: Action history
  - `paused`: Is agent paused?

- `AgentOutput`: LLM response format
  - `current_state`: Agent's understanding of page
  - `action`: List of actions to execute

**How to modify**:
- Add new settings to `AgentSettings`
- Extend state tracking in `AgentState`
- Modify LLM output format in `AgentOutput`

#### **`system_prompt.md`**
**Purpose**: Core instruction prompt that tells the LLM how to behave

**What it does**:
- Explains input format (indexed interactive elements)
- Defines response format (JSON with evaluation, memory, next_goal, action)
- Specifies action sequences and navigation rules
- Sets task completion criteria

**How to modify**:
```python
agent = Agent(
    task=task,
    llm=llm,
    agent_settings=AgentSettings(
        extend_system_message="Additional rules: Never click ads",
        # or completely replace:
        # override_system_message="Your custom prompt"
    )
)
```

#### **`prompts.py`**
**Purpose**: Additional prompt templates

**Contains**:
- System message templates
- Agent message formatting
- Planner prompts

#### **`message_manager/`** subdirectory
**Purpose**: Manages conversation history with LLM

**Files**:
- `service.py`: `MessageManager` class
  - Tracks conversation history
  - Handles token counting
  - Implements procedural memory summaries for long tasks
  - Prevents exceeding context window

**How to modify**:
- Adjust token limits
- Change summarization strategy
- Add custom message filtering

#### **`memory/`** subdirectory
**Purpose**: Long-term memory using mem0ai and FAISS

**Files**:
- `service.py`: Memory service
- `views.py`: Memory configuration

**What it does**:
- Stores past agent experiences
- Retrieves relevant memories for current task
- Uses vector embeddings for semantic search

**How to enable**:
```python
pip install "browser-use[memory]"

agent = Agent(
    task=task,
    llm=llm,
    use_memory=True  # Enable memory
)
```

#### **`playwright_script_generator.py`**
**Purpose**: Generates standalone Playwright scripts from agent history

**What it does**:
- Converts agent action history to Python Playwright code
- Allows you to rerun tasks without LLM
- Useful for creating automated tests

**Usage**:
```python
history = await agent.run()
script = PlaywrightScriptGenerator().generate(history)
print(script)  # Save to .py file
```

#### **`gif.py`**
**Purpose**: Creates animated GIFs from agent execution

**What it does**:
- Takes screenshots from agent history
- Creates animated GIF showing agent's actions

---

### 2. `browser_use/browser/` - Browser Control

Manages browser instances and browser contexts using Playwright.

#### **`browser.py`** (~400 lines)
**Purpose**: `Browser` class - manages Playwright browser instance lifecycle

**What it does**:
- Launches browser (Chromium, Chrome, Firefox)
- Manages browser configuration
- Provides browser context factory

**Configuration via `BrowserConfig`**:
```python
from browser_use import Browser, BrowserConfig

browser = Browser(config=BrowserConfig(
    headless=False,                    # Show browser window
    disable_security=True,             # Allow CORS, etc.
    browser_binary_path="/path/chrome",# Use specific browser
    extra_chromium_args=["--flag"],    # Custom Chrome flags
    wss_url="ws://...",               # Connect to remote browser
    chrome_instance_path="/path",      # Use existing Chrome
))
```

**How to modify**:
- Add new browser types
- Customize launch arguments
- Implement browser pooling

#### **`context.py`** (~1,900 lines)
**Purpose**: `BrowserContext` class - the heart of browser interaction

This is one of the most important files - it handles all browser operations.

**What it does**:
- Manages tabs, navigation, and page state
- Executes controller actions (click, input, scroll, etc.)
- Extracts DOM state and screenshots
- Handles cross-origin iframes
- Screenshot management with element highlighting
- Cookie management
- File downloads

**Key methods**:
```python
async def get_state(use_vision: bool) -> BrowserState:
    # Extracts current page state (DOM + screenshot)

async def execute_action(action: ActionModel) -> ActionResult:
    # Executes an action (click, input, etc.)

async def create_new_tab(url: str) -> int:
    # Opens new tab

async def switch_to_tab(index: int):
    # Switches to different tab
```

**How to modify**:
- Add new low-level browser operations
- Customize screenshot behavior
- Modify DOM extraction logic
- Add custom page event handlers

#### **`chrome.py`**
**Purpose**: Chrome-specific functionality

**What it does**:
- Attach to existing Chrome instance via Chrome DevTools Protocol (CDP)
- Useful for debugging or using your real Chrome profile

**Usage**:
```python
# See examples/browser/real_browser.py
browser = Browser(config=BrowserConfig(
    chrome_instance_path="/path/to/chrome/profile"
))
```

#### **`dolphin_service.py`**
**Purpose**: Integration with Dolphin Anty browser

**What it does**:
- Manages anti-fingerprinting browser profiles
- Useful for scraping that requires unique fingerprints

#### **`views.py`**
**Purpose**: Data models for browser state

**Key models**:
- `TabInfo`: Information about a browser tab
- `BrowserState`: Complete browser state (tabs, DOM, screenshot, URL, etc.)
- `BrowserStateHistory`: Historical state tracking

---

### 3. `browser_use/controller/` - Action System

Defines and manages all available browser actions.

#### **`service.py`** (~800 lines)
**Purpose**: `Controller` class - action registry and executor

**What it does**:
- Registers all default actions (click, input, navigate, scroll, etc.)
- Executes actions through the browser context
- Supports custom action registration via decorators
- Handles output models for structured extraction

**Default actions**:
- `search_google`: Google search
- `go_to_url`: Navigate to URL
- `click_element`: Click element by index
- `input_text`: Type text into element
- `done`: Mark task complete
- `scroll_down/up`: Scroll page
- `switch_tab`: Change tabs
- `open_tab`: Open new tab
- `close_tab`: Close tab
- `extract_page_content`: Get page text
- `send_keys`: Send keyboard keys
- `drag_and_drop`: Drag element to another

**How to add custom actions**:
```python
from browser_use import Controller, BrowserContext
from pydantic import BaseModel

controller = Controller()

class MyActionParams(BaseModel):
    param1: str
    param2: int

@controller.action('Description of my action', param_model=MyActionParams)
async def my_custom_action(params: MyActionParams, browser: BrowserContext):
    # Your custom logic here
    await browser.click(params.param1)
    return f"Clicked {params.param1}"

# Use controller with agent
agent = Agent(task=task, llm=llm, controller=controller)
```

#### **`views.py`**
**Purpose**: Parameter models for all actions

**Contains**:
- `SearchGoogleAction`: Google search parameters
- `GoToUrlAction`: URL navigation
- `ClickElementAction`: Click parameters (index, num_clicks)
- `InputTextAction`: Text input parameters
- `ScrollAction`: Scroll direction and amount
- `DragDropAction`: Drag-drop coordinates
- And more...

**How to modify**:
- Add new parameter models for custom actions
- Extend existing action parameters

#### **`registry/`** subdirectory
**Purpose**: Advanced action registration system

**Files**:
- `service.py`: `Registry` class
- `views.py`: `RegisteredAction`, `ActionModel`, `ActionRegistry` models

**What it does**:
- Supports domain-specific actions (only available on certain websites)
- Supports page-filtered actions (only when page matches criteria)
- Dynamic action availability

**Example - Domain-specific action**:
```python
@controller.action(
    'Search Amazon for product',
    domains=['*.amazon.com', 'amazon.*']
)
async def amazon_search(query: str, browser: BrowserContext):
    # This action only appears when on Amazon
    # LLM only sees it when relevant
    await browser.input_text(0, query)
```

**Example - Page-filtered action**:
```python
@controller.action(
    'Submit form',
    requires_browser=lambda browser: 'form' in browser.state.selector_map
)
async def submit_form(browser: BrowserContext):
    # Only available when form exists on page
    pass
```

---

### 4. `browser_use/dom/` - DOM Processing

Extracts and processes web page DOM for the LLM.

#### **`service.py`** (~204 lines)
**Purpose**: `DomService` class - orchestrates DOM extraction

**What it does**:
- Injects JavaScript into pages
- Executes `buildDomTree.js` to analyze page
- Identifies clickable/interactive elements
- Assigns index numbers to interactive elements
- Handles cross-origin iframes
- Returns optimized DOM representation

**Key methods**:
```python
async def get_clickable_elements() -> dict:
    # Returns map of index -> element info

async def get_dom_state() -> DOMState:
    # Returns complete DOM tree with metadata
```

#### **`buildDomTree.js`** (~1,458 lines)
**CRITICAL FILE** - This JavaScript runs in the browser

**What it does**:
1. Analyzes entire page structure
2. Identifies visible, interactive, and top-layer elements
3. Computes viewport coordinates and element positions
4. Highlights elements with bounding boxes for vision
5. Returns optimized DOM representation to Python

**How it works**:
- Walks DOM tree recursively
- Filters non-visible elements
- Prioritizes interactive elements (buttons, links, inputs)
- Handles shadow DOM
- Detects overlapping elements
- Creates visual highlights for screenshots

**Why it's important**:
- The LLM only "sees" what this script extracts
- Improving this improves agent's understanding of pages
- Most browser-specific logic lives here

**How to modify**:
- Add detection for new element types
- Change element prioritization
- Adjust visibility rules
- Modify highlight styling

#### **`views.py`**
**Purpose**: DOM data structures

**Key models**:
- `DOMElementNode`: Represents HTML elements with metadata
  - `tag_name`: HTML tag
  - `xpath`: XPath selector
  - `attributes`: Element attributes
  - `is_visible`: Visibility status
  - `is_clickable`: Interaction capability
  - `children`: Child nodes

- `DOMTextNode`: Represents text nodes

- `DOMState`: Complete DOM state
  - `element_tree`: Root element
  - `selector_map`: Index -> element mapping for actions
  - `size`: Page dimensions

**How to modify**:
- Add new metadata fields
- Change tree structure
- Add custom element properties

#### **`history_tree_processor/`** subdirectory
**Purpose**: Tracks DOM changes between steps

**What it does**:
- Compares current DOM with previous
- Identifies new vs. existing elements
- Hashes elements for comparison
- Maintains DOM history for agent context

**Why it's useful**:
- Helps LLM understand what changed after actions
- Reduces token usage by highlighting changes
- Improves error recovery

#### **`clickable_element_processor/`** subdirectory
**Purpose**: Optimizes clickable element detection

**What it does**:
- Filters and prioritizes interactive elements
- Reduces noise for LLM
- Improves action selection accuracy

---

### 5. `browser_use/telemetry/` - Analytics

**Purpose**: Collects anonymized usage telemetry

**Files**:
- `service.py`: `ProductTelemetry` class using PostHog
- `views.py`: Telemetry event models

**What it does**:
- Tracks usage patterns (anonymized)
- Helps developers improve library
- Can be disabled via environment variable

**How to disable**:
```bash
# In .env file
ANONYMIZED_TELEMETRY=false
```

---

### 6. Root-level files in `browser_use/`

#### **`__init__.py`**
**Purpose**: Package exports - defines public API

**What it exports**:
```python
from browser_use import (
    Agent,              # Main agent class
    Browser,            # Browser manager
    BrowserConfig,      # Browser configuration
    Controller,         # Action controller
    DomService,         # DOM extraction
    ActionResult,       # Action result type
    # ... and more
)
```

#### **`cli.py`** (~1,200 lines)
**Purpose**: Interactive CLI application using Textual

**What it does**:
- Provides `browser-use` command
- Interactive terminal UI for running agents
- Real-time step visualization
- Conversation history

**Usage**:
```bash
pip install browser-use[cli]
browser-use
```

#### **`utils.py`**
**Purpose**: Utility functions

**Contains**:
- Timing decorators
- Environment checks
- Helper functions

#### **`logging_config.py`**
**Purpose**: Logging configuration

**Environment variable**:
```bash
BROWSER_USE_LOGGING_LEVEL=debug  # result|debug|info
```

#### **`exceptions.py`**
**Purpose**: Custom exceptions

**Contains**:
- `BrowserUseError`: Base exception
- `ActionNotFound`: Invalid action
- And more...

---

## Configuration Files

### **`pyproject.toml`**
**Purpose**: Python package configuration (PEP 621)

**What it defines**:
- Package metadata (name, version, authors)
- Dependencies:
  - `playwright`: Browser automation
  - `langchain-*`: LLM integrations
  - `pydantic`: Data validation
  - `markdownify`: HTML to Markdown
  - `mem0ai`, `faiss-cpu`: Memory system

- Optional dependencies:
  - `[memory]`: Adds `sentence-transformers`
  - `[cli]`: Adds `rich`, `textual`, `click`

- Entry points:
  ```toml
  [project.scripts]
  browseruse = "browser_use.cli:main"
  browser-use = "browser_use.cli:main"
  ```

- Python version: `>=3.11,<4.0`

**How to modify**:
- Add new dependencies
- Change version constraints
- Add new optional dependency groups

### **`.env.example`**
**Purpose**: Template for environment variables

**Variables**:
```bash
# LLM API Keys
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
DEEPSEEK_API_KEY=

# Features
ANONYMIZED_TELEMETRY=true
BROWSER_USE_LOGGING_LEVEL=result
IN_DOCKER=false
```

### **`Dockerfile`**
**Purpose**: Container configuration

**What it does**:
- Base: `python:3.11-slim`
- Installs Playwright and Chromium
- Installs browser-use
- Optimized for multi-arch (amd64/arm64)

**Usage**:
```bash
docker build -t browser-use .
docker run -e OPENAI_API_KEY=xxx browser-use
```

### **`pytest.ini`**
**Purpose**: Test configuration

**Defines**:
- Test markers: `slow`, `integration`, `unit`, `asyncio`
- Async mode: `auto`
- Logging configuration

### **`.pre-commit-config.yaml`**
**Purpose**: Pre-commit hooks for code quality

**Hooks**:
- Ruff linting and formatting
- Trailing whitespace removal
- YAML/JSON validation

---

## Extending the Library

### 1. Adding Custom Actions

**Use case**: Add domain-specific functionality

**Example**: Amazon product search
```python
from browser_use import Agent, Controller, BrowserContext
from pydantic import BaseModel

controller = Controller()

class AmazonSearchParams(BaseModel):
    product_name: str
    max_price: float | None = None

@controller.action(
    'Search for product on Amazon and filter by price',
    param_model=AmazonSearchParams,
    domains=['*.amazon.com']  # Only available on Amazon
)
async def amazon_product_search(params: AmazonSearchParams, browser: BrowserContext):
    # Navigate to Amazon if not already there
    if 'amazon.com' not in browser.current_url:
        await browser.go_to_url('https://amazon.com')

    # Find search box (assuming it's element index 0)
    await browser.input_text(0, params.product_name)

    # Click search button (index 1)
    await browser.click(1)

    # Apply price filter if specified
    if params.max_price:
        # Your custom price filtering logic
        pass

    return f"Searched for {params.product_name}"

# Use with agent
agent = Agent(
    task="Find best laptop under $1000 on Amazon",
    llm=your_llm,
    controller=controller
)
```

### 2. Custom System Prompts

**Use case**: Change agent behavior or add constraints

**Example**: Never click ads
```python
from browser_use import Agent, AgentSettings

custom_instructions = """
IMPORTANT RULES:
- Never click on advertisements
- Always verify you're on the correct domain before entering sensitive info
- If you encounter a CAPTCHA, use the ask_human action to get help
"""

agent = Agent(
    task="Buy shoes online",
    llm=your_llm,
    agent_settings=AgentSettings(
        extend_system_message=custom_instructions,
        max_failures=5  # Allow more retries
    )
)
```

### 3. Using Hooks

**Use case**: Monitor agent, add logging, or implement safety checks

**Example**: Safety hook
```python
from browser_use import Agent

agent = Agent(task=task, llm=llm)

@agent.before_step
async def safety_check(agent_instance):
    """Check agent state before each step"""
    # Get current URL
    state = agent_instance.browser_context.state

    # Prevent accessing certain sites
    forbidden_domains = ['malicious-site.com']
    if any(domain in state.url for domain in forbidden_domains):
        raise Exception(f"Blocked access to forbidden domain: {state.url}")

    print(f"Step {agent_instance.n_steps}: Navigating {state.url}")

@agent.after_step
async def log_actions(agent_instance):
    """Log what happened after each step"""
    last_action = agent_instance.history[-1]
    print(f"Executed: {last_action.action}")
    print(f"Result: {last_action.result}")

await agent.run()
```

### 4. Custom Output Models

**Use case**: Extract structured data

**Example**: Job scraper
```python
from browser_use import Controller
from pydantic import BaseModel

class JobListing(BaseModel):
    title: str
    company: str
    location: str
    salary: str | None
    description: str

controller = Controller(output_model=JobListing)

agent = Agent(
    task="Find software engineer jobs in San Francisco",
    llm=your_llm,
    controller=controller
)

result = await agent.run()
# result.extracted_content will be List[JobListing]
for job in result.extracted_content:
    print(f"{job.title} at {job.company} - {job.salary}")
```

### 5. Memory Integration

**Use case**: Long-running tasks that need context from previous runs

**Example**: Multi-session research
```python
from browser_use import Agent

# First session
agent = Agent(
    task="Research AI companies and remember the top 5",
    llm=your_llm,
    use_memory=True,  # Enable memory
    user_id="researcher_123"  # Unique user ID for memory
)
await agent.run()

# Later session - agent remembers previous research
agent2 = Agent(
    task="Visit the AI companies I researched before and check their careers page",
    llm=your_llm,
    use_memory=True,
    user_id="researcher_123"  # Same user ID
)
await agent2.run()
# Agent will recall the 5 companies from first session
```

### 6. Stealth Mode

**Use case**: Bypass bot detection

**Example**: Stealth browser
```python
from browser_use import Browser, BrowserConfig

browser = Browser(config=BrowserConfig(
    headless=True,
    disable_security=False,
    extra_chromium_args=[
        '--disable-blink-features=AutomationControlled',
    ]
))

agent = Agent(task=task, llm=llm, browser=browser)
```

See `examples/browser/stealth.py` for more stealth techniques.

### 7. File Upload

**Use case**: Upload files during automation

**Example**: Resume uploader
```python
from browser_use import Controller, BrowserContext
from pydantic import BaseModel

controller = Controller()

class UploadFileParams(BaseModel):
    file_path: str
    element_index: int

@controller.action('Upload file to input element', param_model=UploadFileParams)
async def upload_file(params: UploadFileParams, browser: BrowserContext):
    page = browser.get_current_page()

    # Find file input element
    selector_map = browser.state.selector_map
    element_xpath = selector_map[params.element_index]['xpath']

    # Upload file
    await page.set_input_files(f'xpath={element_xpath}', params.file_path)

    return f"Uploaded {params.file_path}"

# Usage
agent = Agent(
    task="Apply to job and upload my resume from /path/to/resume.pdf",
    llm=your_llm,
    controller=controller
)
```

See `examples/custom-functions/file_upload.py` for complete example.

### 8. Clipboard Operations

**Use case**: Copy/paste text

**Example**: Copy email from page
```python
from browser_use import Controller
import pyperclip

controller = Controller()

@controller.action('Copy text to clipboard')
async def copy_to_clipboard(text: str):
    pyperclip.copy(text)
    return f"Copied to clipboard: {text}"

@controller.action('Get clipboard content')
async def get_clipboard():
    return pyperclip.paste()
```

### 9. Parallel Agents

**Use case**: Run multiple agents simultaneously

**Example**: Competitive price checking
```python
import asyncio
from browser_use import Agent

async def check_amazon(product):
    agent = Agent(task=f"Find price of {product} on Amazon", llm=llm)
    return await agent.run()

async def check_ebay(product):
    agent = Agent(task=f"Find price of {product} on eBay", llm=llm)
    return await agent.run()

# Run both in parallel
results = await asyncio.gather(
    check_amazon("laptop"),
    check_ebay("laptop")
)
```

See `examples/features/parallel_agents.py`.

### 10. Export to Playwright Script

**Use case**: Convert agent run to reusable script

**Example**: Record workflow
```python
from browser_use import Agent
from browser_use.agent.playwright_script_generator import PlaywrightScriptGenerator

agent = Agent(task="Login to website and download report", llm=llm)
history = await agent.run()

# Generate Playwright script
generator = PlaywrightScriptGenerator()
script = generator.generate(history)

# Save to file
with open('automation_script.py', 'w') as f:
    f.write(script)

# Now you can run the script without LLM
```

---

## Examples & Tests

### **`examples/`** - 50+ Examples

Organized by category:

#### **`simple.py`**
Basic example - flight search

#### **`browser/`** - Browser features
- `real_browser.py`: Connect to existing Chrome instance
- `stealth.py`: Bypass bot detection
- `using_cdp.py`: Chrome DevTools Protocol

#### **`use-cases/`** - Real-world applications
- `find_and_apply_to_jobs.py`: Job automation
- `shopping.py`: E-commerce automation
- `google_sheets.py`: Google Sheets integration
- `post-twitter.py`: Social media automation
- `captcha.py`: CAPTCHA handling
- And more...

#### **`custom-functions/`** - Extending functionality
- `action_filters.py`: Domain/page-specific actions
- `file_upload.py`: File upload handling
- `clipboard.py`: Clipboard operations
- `hover_element.py`: Custom hover action
- `save_to_file_hugging_face.py`: Data extraction

#### **`features/`** - Advanced features
- `task_with_memory.py`: Long-term memory
- `parallel_agents.py`: Multiple agents
- `playwright_script_generation.py`: Export to Playwright
- `pause_agent.py`: Human-in-the-loop
- `drag_drop.py`: Drag and drop
- Many more...

#### **`models/`** - LLM providers
- `gpt-4o.py`, `claude-3.7-sonnet.py`, `gemini.py`, etc.

#### **`integrations/`**
- `discord/`, `slack/` integrations

### **`tests/`** - Test Suite

30+ test files:
- `test_agent_actions.py`: Agent behavior
- `test_browser.py`: Browser functionality
- `test_controller.py`: Action execution (largest test file)
- `test_context.py`: Context management
- `test_tab_management.py`: Multi-tab scenarios
- `test_models.py`: LLM compatibility
- And more...

**Running tests**:
```bash
pytest                     # All tests
pytest tests/test_agent_actions.py  # Specific test
pytest -m "not slow"      # Skip slow tests
pytest -v                 # Verbose output
```

### **`docs/`** - Documentation

Mintlify-based documentation:

**Structure**:
- `introduction.mdx`: Getting started
- `quickstart.mdx`: Quick start guide
- `development.mdx`: Development guide

**Subdirectories**:
- `customize/`: Agent settings, browser settings, custom functions, hooks, system prompts
- `development/`: Local setup, contribution guide, evaluations
- `cloud/`: Cloud service docs

---

## Development Workflow

### Local Setup

1. **Clone repository**:
```bash
git clone https://github.com/browser-use/browser-use.git
cd browser-use
```

2. **Install dependencies**:
```bash
pip install -e ".[dev,memory,cli]"
playwright install chromium
```

3. **Set up environment**:
```bash
cp .env.example .env
# Add your API keys to .env
```

4. **Run tests**:
```bash
pytest
```

5. **Format code**:
```bash
ruff format .
ruff check . --fix
```

### Making Changes

1. **Find relevant file** (use this guide!)
2. **Make changes**
3. **Add tests** in `tests/`
4. **Run tests**: `pytest`
5. **Format code**: `ruff format .`
6. **Commit**: Follow conventional commits

### Common Modification Patterns

#### Want to change how agent thinks?
→ Modify `browser_use/agent/system_prompt.md` or use `extend_system_message`

#### Want to add new browser action?
→ Add to `browser_use/controller/service.py` via `@controller.action` decorator

#### Want to improve DOM extraction?
→ Modify `browser_use/dom/buildDomTree.js`

#### Want to change browser behavior?
→ Modify `browser_use/browser/context.py`

#### Want to add new LLM provider?
→ Use LangChain's provider (e.g., `langchain-xyz`), add to `pyproject.toml`

#### Want to change action parameters?
→ Modify models in `browser_use/controller/views.py`

#### Want to track new metrics?
→ Add to `browser_use/telemetry/views.py`

---

## Architecture Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. User defines task                                        │
│    agent = Agent(task="...", llm=...)                       │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ 2. Agent.run() - Main Loop                                  │
│    ┌──────────────────────────────────────────────┐         │
│    │ a. Extract DOM state (DomService)            │         │
│    │    - buildDomTree.js finds interactive elems │         │
│    │    - Assigns index numbers                   │         │
│    │    - Takes screenshot with highlights        │         │
│    ├──────────────────────────────────────────────┤         │
│    │ b. Create LLM context (MessageManager)       │         │
│    │    - Format DOM state                        │         │
│    │    - Add screenshot (if vision enabled)      │         │
│    │    - Include conversation history            │         │
│    │    - Add available actions                   │         │
│    ├──────────────────────────────────────────────┤         │
│    │ c. Get LLM decision                          │         │
│    │    - LLM analyzes state                      │         │
│    │    - Returns JSON with actions               │         │
│    ├──────────────────────────────────────────────┤         │
│    │ d. Execute actions (Controller)              │         │
│    │    - Parse action parameters                 │         │
│    │    - Execute via BrowserContext              │         │
│    │    - Collect results                         │         │
│    ├──────────────────────────────────────────────┤         │
│    │ e. Update state                              │         │
│    │    - Record action in history                │         │
│    │    - Store in memory (if enabled)            │         │
│    │    - Check if task is done                   │         │
│    ├──────────────────────────────────────────────┤         │
│    │ f. Repeat until:                             │         │
│    │    - Task complete (done action called)      │         │
│    │    - Max steps reached                       │         │
│    │    - Too many failures                       │         │
│    └──────────────────────────────────────────────┘         │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ 3. Return results                                           │
│    - AgentHistoryList with full execution trace            │
│    - Screenshots, actions, results for each step           │
│    - Extracted data (if output_model specified)            │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Dependencies Explained

### **Playwright** (`playwright >= 1.52.0`)
- **What**: Browser automation library by Microsoft
- **Why**: Reliable, fast, supports multiple browsers
- **Used for**: All browser control (navigate, click, type, screenshot)

### **LangChain** (`langchain-core`, `langchain-openai`, etc.)
- **What**: Framework for LLM applications
- **Why**: Unified interface for different LLM providers
- **Used for**: Communicating with GPT-4, Claude, Gemini, etc.

### **Pydantic** (`pydantic >= 2.10.4`)
- **What**: Data validation library
- **Why**: Type-safe configs, LLM output parsing
- **Used for**: All data models (AgentSettings, ActionModel, etc.)

### **markdownify** (`markdownify == 1.1.0`)
- **What**: HTML to Markdown converter
- **Why**: Simplifies HTML for LLM processing
- **Used for**: Extract page content action

### **mem0ai** + **faiss-cpu**
- **What**: Memory and vector search libraries
- **Why**: Long-term memory for agents
- **Used for**: Storing and retrieving past experiences

### **Textual** + **Rich** (optional)
- **What**: Terminal UI libraries
- **Why**: Interactive CLI experience
- **Used for**: `browser-use` CLI command

---

## Troubleshooting Common Modifications

### Agent keeps making mistakes
**Solution**:
1. Improve system prompt with specific instructions
2. Use `extend_system_message` to add rules
3. Check if DOM extraction is missing elements (modify `buildDomTree.js`)
4. Enable vision mode: `AgentSettings(use_vision=True)`

### Can't click certain elements
**Solution**:
1. Check if element is in `selector_map` (run with debug logging)
2. Modify `buildDomTree.js` to detect that element type
3. Add custom action with XPath selector

### Out of tokens
**Solution**:
1. Reduce `max_input_tokens` in `AgentSettings`
2. Enable DOM history processor to reduce redundant info
3. Disable vision if not needed

### Need to bypass bot detection
**Solution**:
1. Use stealth mode (see `examples/browser/stealth.py`)
2. Connect to real Chrome profile (`chrome_instance_path`)
3. Add custom headers/user agent

### Need human help during automation
**Solution**:
1. Use pause hook: `examples/features/pause_agent.py`
2. Add custom action that calls `ask_human`

---

## Summary

This project is highly modular and extensible. Key modification points:

1. **Custom Actions**: `@controller.action` decorator
2. **System Prompts**: `AgentSettings.extend_system_message`
3. **Hooks**: `@agent.before_step`, `@agent.after_step`
4. **DOM Extraction**: Modify `buildDomTree.js`
5. **Browser Behavior**: Extend `BrowserContext` class
6. **Output Parsing**: Use `output_model` parameter
7. **Memory**: Enable with `use_memory=True`

The codebase is well-documented with extensive examples. Start by running examples, then modify them for your use case. Most customization can be done without touching core library code - use the extension points (actions, hooks, settings) first.

For questions, join the [Discord](https://link.browser-use.com/discord) or check the [docs](https://docs.browser-use.com).

Happy automating!
