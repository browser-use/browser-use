# Browser-Use Project Understanding

## What is Browser-Use?

**Browser-Use** is an async Python library (>=3.11) that enables AI agents to control web browsers using LLMs + Playwright. It's essentially a bridge between AI models and browser automation, making websites accessible for AI agents.

## Core Architecture (Service-Oriented Design)

The project follows a clean service-oriented architecture with these main components:

### 1. **Agent** - file:///D:/browser-use/browser_use/agent/service.py

- **Main orchestrator** that executes browser automation tasks
- Uses LLM to interpret natural language tasks and generate browser actions
- Manages conversation history and action execution
- Entry point for most operations

### 2. **Controller** - file:///D:/browser-use/browser_use/controller/service.py

- **Action execution hub** that bridges agent decisions → browser operations
- Registry system for managing custom functions and actions
- Handles the actual execution of browser commands

### 3. **Browser Session** - file:///D:/browser-use/browser_use/browser/session.py

- **Browser management layer** wrapping Playwright
- Handles browser profiles, contexts, session management
- Provides browser automation primitives (click, type, navigate, etc.)

### 4. **DOM Service** - file:///D:/browser-use/browser_use/dom/service.py

- **DOM processor** that extracts and processes web page information for LLM consumption
- Handles element selection, viewport info, accessibility trees
- Makes web pages "readable" for AI models

### 5. **LLM Integrations** - file:///D:/browser-use/browser_use/llm/

- **Multi-provider chat interfaces** supporting OpenAI, Anthropic, Google, Groq, Azure, Ollama
- Each provider has its own module with specialized serialization

## Key Design Patterns

- **Lazy Loading**: Heavy dependencies loaded only when needed
- **Service/Views Pattern**: Logic in `service.py`, Pydantic models in `views.py`
- **Event Bus**: Uses `bubus` for event-driven communication
- **Registry System**: Extensible action registration for custom functions

## Project Structure Overview

```
browser-use/
├── browser_use/          # Main library code
│   ├── agent/           # AI orchestration layer
│   ├── browser/         # Playwright wrapper & session management
│   ├── controller/      # Action execution & registry
│   ├── dom/            # DOM processing & extraction
│   ├── llm/            # Multi-provider LLM interfaces
│   ├── mcp/            # MCP (Model Context Protocol) server
│   ├── integrations/   # Gmail, Slack, etc.
│   └── cli.py          # Command-line interface
├── examples/           # Usage examples & demos
├── tests/             # Test suite (CI tests in tests/ci/)
└── docs/              # Documentation
```

## How It Works

1. **User gives natural language task** → Agent
2. **Agent uses LLM** to understand task and plan actions
3. **Controller executes actions** via Browser Session
4. **DOM Service extracts page state** for LLM feedback
5. **Repeat until task complete**

## Key Features

- **Multi-LLM Support**: Works with OpenAI, Anthropic, Google, Groq, Azure, Ollama
- **Browser Automation**: Full Playwright integration for real browser control
- **Custom Functions**: Extensible registry for domain-specific actions
- **MCP Integration**: Model Context Protocol server/client support
- **CLI Interface**: Command-line tool for interactive usage
- **Cloud Support**: Hosted version available
- **Rich Examples**: Extensive example library for various use cases

## Development Workflow

- **Testing**: `uv run pytest -vxs tests/ci`
- **Type Checking**: `uv run pyright`
- **Linting**: `uv run ruff check` and `uv run ruff format`
- **Installation**: `pip install "browser-use[cli]"`
- **Browser Setup**: `playwright install chromium --with-deps --no-shell`

## Architecture Philosophy

The system is designed to be:

- **Ergonomic**: Easy to use APIs
- **Intuitive**: Matches mental models
- **Hard to get wrong**: Defensive design
- **Extensible**: Plugin architecture for custom functions
- **Observable**: Rich telemetry and logging support

This is a sophisticated browser automation framework that puts AI in the driver's seat, making web interaction as simple as describing what you want to accomplish.

---

# DETAILED CORE ARCHITECTURE ANALYSIS

## 1. AGENT CLASS

**Main File**: file:///D:/browser-use/browser_use/agent/service.py#L133 (class Agent)
**Views/Models**: file:///D:/browser-use/browser_use/agent/views.py#L28 (AgentSettings)

### Key Components:

- **Main Orchestrator**: The `Agent[Context, AgentStructuredOutput]` class is the primary entry point
- **Generic Types**: Supports typed contexts and structured outputs via generics
- **Core Dependencies**:
  - `llm: BaseChatModel` - LLM provider interface - file:///D:/browser-use/browser_use/llm/base.py
  - `controller: Controller[Context]` - Action execution hub - file:///D:/browser-use/browser_use/controller/service.py#L49
  - `browser_session: BrowserSession` - Browser management layer - file:///D:/browser-use/browser_use/browser/session.py

### Agent State Management:

**File**: file:///D:/browser-use/browser_use/agent/views.py#L82 (class AgentState)

```python
class AgentState:
    thinking: str               # LLM reasoning process
    evaluation_previous_goal: str  # Assessment of previous actions
    memory: str                # Long-term context memory
    next_goal: str             # Current objective
    action: ActionModel        # Next action to execute
```

### Core Agent Methods:

#### `async def run(max_steps=100) -> AgentHistoryList`

**Location**: file:///D:/browser-use/browser_use/agent/service.py#L654
**Main execution loop:**

1. Sets up signal handlers (CTRL+C handling)
2. Initializes browser session if needed
3. Calls `step()` repeatedly until task completion or max_steps
4. Handles errors and cleanup

#### `async def step() -> None`

**Location**: file:///D:/browser-use/browser_use/agent/service.py#L758
**Single step execution pipeline:**

1. **Prepare Context** (`_prepare_context()`) - file:///D:/browser-use/browser_use/agent/service.py#L802
   - Gets current browser state via `BrowserSession`
   - Extracts DOM info via `DomService`
   - Builds conversation history
2. **Get Next Action** (`_get_next_action()`) - file:///D:/browser-use/browser_use/agent/service.py#L890
   - Sends context to LLM
   - Parses response into `AgentOutput`
   - Validates action parameters
3. **Execute Actions** (`_execute_actions()`) - file:///D:/browser-use/browser_use/agent/service.py#L1020
   - Delegates to `Controller.execute_action()`
   - Handles action results and errors
4. **Post Process** (`_post_process()`) - file:///D:/browser-use/browser_use/agent/service.py#L1100
   - Updates conversation history
   - Saves screenshots/traces
   - Logs telemetry

### Key Agent Features:

- **Vision Support**: Screenshots sent to LLM for visual understanding
- **Memory Management**: Maintains conversation context and long-term memory
- **Error Recovery**: Retries failed actions with exponential backoff
- **Structured Output**: Supports typed response schemas
- **File System**: Integrated file operations via `FileSystem` - file:///D:/browser-use/browser_use/filesystem/file_system.py
- **Telemetry**: Rich observability via `ProductTelemetry` - file:///D:/browser-use/browser_use/telemetry/service.py

## 2. CONTROLLER CLASS

**Main File**: file:///D:/browser-use/browser_use/controller/service.py#L49 (class Controller)
**Views/Models**: file:///D:/browser-use/browser_use/controller/views.py (action parameter models)
**Registry**: file:///D:/browser-use/browser_use/controller/registry/service.py#L44 (class Registry)

### Core Responsibility:

**Action Execution Hub** - Bridges between Agent decisions and browser operations

### Key Components:

- **Registry**: `Registry[Context]` - Manages all available actions - file:///D:/browser-use/browser_use/controller/registry/service.py#L44
- **Generic Context**: Supports typed context passing between actions
- **Default Actions**: Pre-registered browser automation primitives

### Built-in Actions (Pre-registered):

**Location**: file:///D:/browser-use/browser_use/controller/service.py#L64 - file:///D:/browser-use/browser_use/controller/service.py#L400

```python
# Navigation
@registry.action("Search the query in Google")  # Line 64
async def search_google(params: SearchGoogleAction, browser_session: BrowserSession)

@registry.action("Navigate to URL")  # Line 86
async def go_to_url(params: GoToUrlAction, browser_session: BrowserSession)

# Interaction
@registry.action("Click on element")  # Line 120
async def click_element(params: ClickElementAction, browser_session: BrowserSession)

@registry.action("Type text into element")  # Line 180
async def input_text(params: InputTextAction, browser_session: BrowserSession)

# Completion
@registry.action("Task completed")  # Line 61
async def done(params: DoneAction, browser_session: BrowserSession)
```

### Action Execution Flow:

**Main Method**: `Controller.execute_action()` - file:///D:/browser-use/browser_use/controller/service.py#L421

1. **Action Resolution**: Registry finds action by name
2. **Parameter Validation**: Pydantic models validate parameters
3. **Context Injection**: Browser session and context automatically injected
4. **Execution**: Action function called with validated parameters
5. **Result Processing**: `ActionResult` returned with extracted content

### Registry System:

**Main File**: file:///D:/browser-use/browser_use/controller/registry/service.py#L44
**Views**: file:///D:/browser-use/browser_use/controller/registry/views.py#L12 (ActionModel)

- **Dynamic Registration**: Actions registered via decorators (`registry.action()`)
- **Type Safety**: Full Pydantic validation for all parameters
- **Context Awareness**: Automatic dependency injection
- **Extensibility**: Custom functions can be registered at runtime

## 3. BROWSER SESSION CLASS

**Main File**: file:///D:/browser-use/browser_use/browser/session.py#L189 (class BrowserSession)
**Views/Models**: file:///D:/browser-use/browser_use/browser/views.py (PageInfo, TabInfo, BrowserStateSummary)
**Profile**: file:///D:/browser-use/browser_use/browser/profile.py#L15 (BrowserProfile)
**Types**: file:///D:/browser-use/browser_use/browser/types.py (Browser, BrowserContext, Page)

### Core Responsibility:

**Browser Management Layer** - Wraps Playwright with browser-use specific functionality

### Key Components:

**Location**: file:///D:/browser-use/browser_use/browser/session.py#L189

```python
class BrowserSession:
    browser: Browser                    # Playwright browser instance
    context: BrowserContext            # Browser context (session)
    tabs: list[Page]                   # All open tabs/pages
    current_tab_index: int             # Active tab
    profile: BrowserProfile            # User profile settings
    allowed_domains: list[str]         # Security whitelist
```

### Browser Lifecycle Management:

- **Initialization**: Creates browser, context, and initial page (`__init__()` - Line 220)
- **Profile Management**: Handles user data, cookies, extensions
- **Tab Management**: Multi-tab support with switching capabilities
- **Security**: Domain validation and URL filtering (`_is_url_allowed()` - Line 450)
- **Resource Management**: Proper cleanup and error recovery (`close()` - Line 380)

### Key Browser Methods:

#### `async def get_current_page() -> Page`

**Location**: file:///D:/browser-use/browser_use/browser/session.py#L495
Returns active Playwright page for DOM operations

#### `async def navigate_to(url: str) -> None`

**Location**: file:///D:/browser-use/browser_use/browser/session.py#L520
Navigates current tab with domain validation and error handling

#### `async def create_new_tab(url: str) -> Page`

**Location**: file:///D:/browser-use/browser_use/browser/session.py#L565
Opens new tab with security checks

#### `async def take_screenshot() -> bytes`

**Location**: file:///D:/browser-use/browser_use/browser/session.py#L645
Captures page screenshot for LLM vision

#### `async def get_page_info() -> PageInfo`

**Location**: file:///D:/browser-use/browser_use/browser/session.py#L680
Extracts page metadata (title, URL, etc.)

### Health Monitoring:

**Decorator**: `@require_healthy_browser` - file:///D:/browser-use/browser_use/browser/session.py#L92

- **Crash Detection**: Monitors page health and recovers from crashes
- **Performance**: Tracks memory usage and performance metrics
- **Error Recovery**: Automatic retry mechanisms for flaky operations

## 4. DOM SERVICE CLASS

**Main File**: file:///D:/browser-use/browser_use/dom/service.py#L27 (class DomService)
**Views/Models**: file:///D:/browser-use/browser_use/dom/views.py (DOMState, DOMElementNode, SelectorMap)
**JavaScript Engine**: file:///D:/browser-use/browser_use/dom/dom_tree/index.js (DOM extraction script)
**History Processor**: file:///D:/browser-use/browser_use/dom/history_tree_processor/service.py#L15 (HistoryTreeProcessor)

### Core Responsibility:

**DOM Processing Engine** - Makes web pages readable for LLMs

### Architecture:

**Location**: file:///D:/browser-use/browser_use/dom/service.py#L27

```python
class DomService:
    page: Page                    # Playwright page reference
    js_code: str                 # Injected JavaScript for DOM extraction
    xpath_cache: dict            # Performance optimization cache
```

### DOM Extraction Pipeline:

#### `async def get_clickable_elements() -> DOMState`

**Location**: file:///D:/browser-use/browser_use/dom/service.py#L38
**Main DOM extraction method:**

1. **JavaScript Injection**: Injects `dom_tree/index.js` into page (`_build_dom_tree()` - Line 67)
2. **DOM Tree Building**: Extracts element hierarchy with attributes
3. **Clickable Detection**: Identifies interactive elements
4. **Viewport Filtering**: Only includes visible elements
5. **Selector Mapping**: Creates XPath/CSS selector mappings

#### DOM Tree Structure:

**Location**: file:///D:/browser-use/browser_use/dom/views.py#L45 (class DOMElementNode)

```python
class DOMElementNode:
    tag_name: str               # HTML tag (div, button, etc.)
    xpath: str                  # Unique element selector
    attributes: dict            # HTML attributes (id, class, etc.)
    children: list[DOMBaseNode] # Child elements/text nodes
    is_visible: bool            # Visibility state
    parent: DOMElementNode | None # Parent reference
```

### Advanced DOM Features:

- **Cross-Origin iFrames**: Detects and handles embedded content (`get_cross_origin_iframes()` - Line 49)
- **Accessibility Tree**: Extracts ARIA attributes and roles
- **Dynamic Content**: Handles JavaScript-rendered content
- **Element Highlighting**: Visual feedback for debugging
- **Performance Optimization**: Caching and selective extraction (`xpath_cache`)

## 5. LLM INTEGRATION LAYER

**Base Interface**: file:///D:/browser-use/browser_use/llm/base.py#L14 (class BaseChatModel)
**Message Types**: file:///D:/browser-use/browser_use/llm/messages.py (BaseMessage, UserMessage, etc.)
**Schema**: file:///D:/browser-use/browser_use/llm/schema.py (response validation schemas)

### Multi-Provider Architecture:

Each provider implements `BaseChatModel` interface:

- **Anthropic**: file:///D:/browser-use/browser_use/llm/anthropic/chat.py#L15 (class ChatAnthropic)
- **OpenAI**: file:///D:/browser-use/browser_use/llm/openai/chat.py#L20 (class ChatOpenAI)
- **Google**: file:///D:/browser-use/browser_use/llm/google/chat.py#L18 (class ChatGoogle)
- **Groq**: file:///D:/browser-use/browser_use/llm/groq/chat.py#L15 (class ChatGroq)
- **Ollama**: file:///D:/browser-use/browser_use/llm/ollama/chat.py#L12 (class ChatOllama)
- **Azure**: file:///D:/browser-use/browser_use/llm/azure/chat.py#L15 (class ChatAzure)
- **AWS Bedrock**: file:///D:/browser-use/browser_use/llm/aws/chat_bedrock.py#L15 (class ChatBedrockAnthropic)

### Unified Interface:

**Location**: file:///D:/browser-use/browser_use/llm/base.py#L14

```python
class BaseChatModel:
    async def invoke(messages: list[BaseMessage]) -> BaseMessage  # Line 25
    def get_token_count(text: str) -> int                        # Line 35
    supports_vision: bool                                        # Line 40
```

### Provider-Specific Features:

- **Serializers**: Each provider has custom serialization (`*/serializer.py`)
- **Token Counting**: Provider-specific token calculation methods
- **Vision Support**: Multi-modal capabilities for image understanding
- **Streaming**: Real-time response streaming support

---

# END-TO-END EXECUTION FLOW

## 1. INITIALIZATION PHASE

**Entry Point**: User code creates `Agent()` instance

```
User Code → Agent.__init__() - file:///D:/browser-use/browser_use/agent/service.py#L133
├── Creates Controller with Registry - file:///D:/browser-use/browser_use/controller/service.py#L49
├── Initializes BrowserSession - file:///D:/browser-use/browser_use/browser/session.py#L189
├── Sets up LLM provider - file:///D:/browser-use/browser_use/llm/base.py#L14
└── Configures AgentSettings - file:///D:/browser-use/browser_use/agent/views.py#L28
```

## 2. TASK EXECUTION PHASE

**Main Method**: `Agent.run()` - file:///D:/browser-use/browser_use/agent/service.py#L654

```
Agent.run() [Line 654]
├── Browser Session Setup [Line 690]
│   ├── Launch browser (Chrome/Firefox) [BrowserSession.__init__]
│   ├── Create context with profile - file:///D:/browser-use/browser_use/browser/profile.py
│   └── Open initial page/tab - file:///D:/browser-use/browser_use/browser/session.py#L300
├── Main Loop (until done or max_steps) [Line 720]
│   └── Agent.step() [CORE PIPELINE - Line 758]
└── Cleanup & Results [Line 780]
```

## 3. SINGLE STEP PIPELINE

**Main Method**: `Agent.step()` - file:///D:/browser-use/browser_use/agent/service.py#L758

### Phase 1: Context Preparation

**Method**: `Agent._prepare_context()` - file:///D:/browser-use/browser_use/agent/service.py#L802

```
Agent._prepare_context() [Line 802]
├── BrowserSession.get_current_page() - file:///D:/browser-use/browser_use/browser/session.py#L495
├── DomService.get_clickable_elements() - file:///D:/browser-use/browser_use/dom/service.py#L38
│   ├── Inject JavaScript into page - file:///D:/browser-use/browser_use/dom/dom_tree/index.js
│   ├── Extract DOM tree + selectors [_build_dom_tree() - Line 67]
│   └── Return DOMState object - file:///D:/browser-use/browser_use/dom/views.py#L20
├── Build conversation history [MessageManager] - file:///D:/browser-use/browser_use/agent/message_manager/service.py
└── Create system prompt with context [SystemPrompt] - file:///D:/browser-use/browser_use/agent/prompts.py
```

### Phase 2: LLM Decision Making

**Method**: `Agent._get_next_action()` - file:///D:/browser-use/browser_use/agent/service.py#L890

```
Agent._get_next_action() [Line 890]
├── Prepare messages for LLM [Line 900]
│   ├── System prompt (task + capabilities) - file:///D:/browser-use/browser_use/agent/prompts.py
│   ├── DOM state (clickable elements) - file:///D:/browser-use/browser_use/dom/views.py
│   ├── Screenshot (if vision enabled) [BrowserSession.take_screenshot()]
│   └── Conversation history [MessageManager.get_messages()]
├── LLM.invoke(messages) - file:///D:/browser-use/browser_use/llm/base.py#L25
│   ├── Provider-specific API call [*/chat.py in each llm provider]
│   ├── Parse JSON response [*/serializer.py]
│   └── Validate against schema - file:///D:/browser-use/browser_use/llm/schema.py
└── Extract AgentOutput - file:///D:/browser-use/browser_use/agent/views.py#L125
    ├── thinking: str (reasoning)
    ├── next_goal: str (objective)
    ├── action: ActionModel (what to do)
    └── memory: str (context update)
```

### Phase 3: Action Execution

**Method**: `Agent._execute_actions()` - file:///D:/browser-use/browser_use/agent/service.py#L1020

```
Agent._execute_actions() [Line 1020]
├── Controller.execute_action(action) - file:///D:/browser-use/browser_use/controller/service.py#L421
│   ├── Registry.find_action(action.name) - file:///D:/browser-use/browser_use/controller/registry/service.py#L80
│   ├── Validate action parameters [Pydantic models] - file:///D:/browser-use/browser_use/controller/views.py
│   ├── Inject dependencies (browser_session, context) [Registry._execute() - Line 120]
│   └── Execute action function [Pre-registered actions - Lines 64-400]
│       ├── BrowserSession methods (click, type, navigate)
│       ├── DOM manipulation via Playwright - file:///D:/browser-use/browser_use/browser/types.py
│       └── Return ActionResult - file:///D:/browser-use/browser_use/agent/views.py#L15
├── Process ActionResult [Line 1050]
│   ├── Extract content/data
│   ├── Update memory [MessageManager.add_message()]
│   └── Log telemetry - file:///D:/browser-use/browser_use/telemetry/service.py
└── Handle errors/retries [Line 1080]
```

### Phase 4: Post Processing

**Method**: `Agent._post_process()` - file:///D:/browser-use/browser_use/agent/service.py#L1100

```
Agent._post_process() [Line 1100]
├── Update conversation history [MessageManager] - file:///D:/browser-use/browser_use/agent/message_manager/service.py
├── Save screenshots/traces (if enabled) [Line 1120]
├── Log telemetry events [ProductTelemetry] - file:///D:/browser-use/browser_use/telemetry/service.py
├── Check completion conditions [Line 1140]
└── Prepare for next step [Line 1150]
```

## COMPONENT COMMUNICATION FLOW

```
┌─────────┐    ┌──────────────┐    ┌─────────────┐
│  User   │───▶│    Agent     │───▶│ Controller  │
│  Task   │    │(Orchestrator)│    │(Executor)   │
└─────────┘    └──────┬───────┘    └─────┬───────┘
                      │                  │
                      ▼                  ▼
              ┌───────────────┐   ┌─────────────┐
              │ BrowserSession│   │  Registry   │
              │   (Browser)   │   │ (Actions)   │
              └───────┬───────┘   └─────────────┘
                      │
                      ▼
              ┌───────────────┐
              │  DomService   │
              │ (Page Parser) │
              └───────────────┘
                      │
                      ▼
              ┌───────────────┐
              │   Playwright  │
              │ (Browser API) │
              └───────────────┘
```

## KEY INTEGRATION POINTS

1. **Agent ↔ LLM**: Structured prompts with DOM context + vision

   - `Agent._get_next_action()` → `BaseChatModel.invoke()` - file:///D:/browser-use/browser_use/agent/service.py#L890 → file:///D:/browser-use/browser_use/llm/base.py#L25

2. **Agent ↔ Controller**: Action dispatching with type safety

   - `Agent._execute_actions()` → `Controller.execute_action()` - file:///D:/browser-use/browser_use/agent/service.py#L1020 → file:///D:/browser-use/browser_use/controller/service.py#L421

3. **Controller ↔ Registry**: Dynamic action resolution

   - `Controller.execute_action()` → `Registry.find_action()` - file:///D:/browser-use/browser_use/controller/service.py#L421 → file:///D:/browser-use/browser_use/controller/registry/service.py#L80

4. **Controller ↔ BrowserSession**: Browser primitive execution

   - Action functions → `BrowserSession` methods (via dependency injection) - file:///D:/browser-use/browser_use/controller/service.py#L64 - file:///D:/browser-use/browser_use/controller/service.py#L400

5. **BrowserSession ↔ DomService**: Page state extraction

   - `Agent._prepare_context()` → `DomService.get_clickable_elements()` - file:///D:/browser-use/browser_use/agent/service.py#L802 → file:///D:/browser-use/browser_use/dom/service.py#L38

6. **DomService ↔ Playwright**: Low-level browser automation

   - `DomService._build_dom_tree()` → JavaScript injection - file:///D:/browser-use/browser_use/dom/service.py#L67 → file:///D:/browser-use/browser_use/dom/dom_tree/index.js

7. **Agent ↔ Telemetry**: Observability and debugging
   - Throughout Agent lifecycle → `ProductTelemetry` events - file:///D:/browser-use/browser_use/telemetry/service.py

---

# QUICK REFERENCE - ENTRY POINTS FOR DEVELOPMENT

## Main Classes to Start With:

- **Agent Class**: file:///D:/browser-use/browser_use/agent/service.py#L133 - Main orchestrator
- **Controller Class**: file:///D:/browser-use/browser_use/controller/service.py#L49 - Action executor
- **BrowserSession Class**: file:///D:/browser-use/browser_use/browser/session.py#L189 - Browser manager
- **DomService Class**: file:///D:/browser-use/browser_use/dom/service.py#L27 - DOM processor
- **Registry Class**: file:///D:/browser-use/browser_use/controller/registry/service.py#L44 - Action registry

## Key Configuration Files:

- **Agent Settings**: file:///D:/browser-use/browser_use/agent/views.py#L28 (AgentSettings)
- **System Prompts**: file:///D:/browser-use/browser_use/agent/prompts.py + file:///D:/browser-use/browser_use/agent/system_prompt.md
- **Action Models**: file:///D:/browser-use/browser_use/controller/views.py (parameter models)
- **DOM Models**: file:///D:/browser-use/browser_use/dom/views.py (DOM tree structures)
- **LLM Interface**: file:///D:/browser-use/browser_use/llm/base.py#L14 (BaseChatModel)

## Critical JavaScript:

- **DOM Extraction**: file:///D:/browser-use/browser_use/dom/dom_tree/index.js - Core DOM processing logic

## Examples & Tests:

- **Examples**: file:///D:/browser-use/examples/ - Usage patterns and integrations
- **Tests**: file:///D:/browser-use/tests/ci/ - Core functionality tests
