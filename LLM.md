# Browser-Use Python Library - Complete API Documentation

## Overview

Browser-use is a Python library that enables AI agents to control web browsers through natural language instructions. It provides a comprehensive API for browser automation, DOM manipulation, and LLM integration.

**Version:** 0.5.4  
**Python Requirements:** >=3.11,<4.0  
**License:** MIT  
**Repository:** https://github.com/browser-use/browser-use

## Installation

```bash
pip install browser-use
playwright install chromium --with-deps --no-shell
```

## Quick Start

```python
import asyncio
from browser_use import Agent
from browser_use.llm import ChatOpenAI

async def main():
    agent = Agent(
        task="Navigate to Google and search for 'Python'",
        llm=ChatOpenAI(model="gpt-4"),
    )
    await agent.run()

asyncio.run(main())
```

## Core Components

### Main Imports

```python
from browser_use import (
    # Core classes
    Agent, Browser, BrowserSession, BrowserProfile, BrowserContext,
    Controller, DomService, SystemPrompt,
    
    # Data models
    ActionModel, ActionResult, AgentHistoryList,
    
    # LLM integrations
    ChatOpenAI, ChatAnthropic, ChatGoogle, ChatGroq, ChatOllama,
    ChatAzureOpenAI
)
```


# Agent API

## Agent Class

**Import:** `from browser_use import Agent`

The main class for creating AI-powered browser automation agents.

### Constructor

```python
class Agent(Generic[Context, AgentStructuredOutput]):
    def __init__(
        self,
        task: str,
        llm: BaseChatModel,
        # Browser configuration
        page: Page | None = None,
        browser: Browser | BrowserSession | None = None,
        browser_context: BrowserContext | None = None,
        browser_profile: BrowserProfile | None = None,
        browser_session: BrowserSession | None = None,
        controller: Controller[Context] | None = None,
        # Agent settings
        use_vision: bool = True,
        max_failures: int = 3,
        retry_delay: int = 10,
        max_actions_per_step: int = 10,
        use_thinking: bool = True,
        max_history_items: int = 40,
        images_per_step: int = 1,
        calculate_cost: bool = False,
        # Callbacks and customization
        save_conversation_path: str | Path | None = None,
        generate_gif: bool | str = False,
        override_system_message: str | None = None,
        extend_system_message: str | None = None,
        **kwargs
    )
```

**Key Parameters:**
- `task` (str): Natural language description of what the agent should do
- `llm` (BaseChatModel): Language model for decision making
- `use_vision` (bool): Enable screenshot analysis (default: True)
- `max_failures` (int): Max consecutive failures before stopping (default: 3)
- `max_actions_per_step` (int): Max actions per step (default: 10)
- `use_thinking` (bool): Include reasoning in responses (default: True)

### Main Methods

#### `async def run(max_steps: int = 100) -> AgentHistoryList`
Execute the agent's task.

```python
history = await agent.run(max_steps=10)
if history.is_successful():
    print(f"Task completed: {history.final_result()}")
```

#### `async def step() -> None`
Execute one step of the task.

#### `async def multi_act(actions: list[ActionModel]) -> list[ActionResult]`
Execute multiple actions in sequence.

#### Control Methods
```python
def pause() -> None
def resume() -> None
def stop() -> None
async def close() -> None
```

#### History Management
```python
def save_history(file_path: str | Path | None = None) -> None
async def load_and_rerun(history_file: str | Path | None = None) -> list[ActionResult]
```

## Data Models

### AgentHistoryList

```python
class AgentHistoryList(BaseModel):
    history: list[AgentHistory]
    usage: UsageSummary | None = None
    
    def total_duration_seconds(self) -> float
    def save_to_file(self, filepath: str | Path) -> None
    def is_done(self) -> bool
    def is_successful(self) -> bool | None
    def has_errors(self) -> bool
    def errors(self) -> list[str | None]
    def final_result(self) -> None | str
```

### ActionResult

```python
class ActionResult(BaseModel):
    is_done: bool | None = False
    success: bool | None = None
    error: str | None = None
    extracted_content: str | None = None
```

### AgentSettings

```python
class AgentSettings(BaseModel):
    use_vision: bool = True
    max_failures: int = 3
    retry_delay: int = 10
    max_actions_per_step: int = 10
    use_thinking: bool = True
    max_history_items: int = 40
    images_per_step: int = 1
    calculate_cost: bool = False
```


# Browser Management API

## BrowserSession Class

**Import:** `from browser_use import BrowserSession`

Main class for browser automation and session management.

### Constructor

```python
class BrowserSession(BaseModel):
    def __init__(
        self,
        browser_profile: BrowserProfile | None = None,
        wss_url: str | None = None,
        cdp_url: str | None = None,
        browser_pid: int | None = None,
        **kwargs
    )
```

### Session Management

#### `async def start() -> Self`
Start the browser session.

```python
browser = BrowserSession()
await browser.start()
```

#### `async def stop() -> None`
Stop the browser session.

#### Context Manager Support
```python
async with BrowserSession() as browser:
    # Browser automatically started and stopped
    state = await browser.get_state_summary()
```

### Page Navigation

#### `async def get_current_page() -> Page`
Get the current active page.

#### `async def switch_to_tab(page_id: int) -> Page`
Switch to a specific tab.

#### `async def get_tabs_info() -> list[TabInfo]`
Get information about all open tabs.

```python
class TabInfo(BaseModel):
    page_id: int
    url: str
    title: str
```

### State Management

#### `async def get_state_summary() -> BrowserStateSummary`
Get comprehensive browser state including DOM, screenshot, and page info.

```python
state = await browser.get_state_summary()
print(f"URL: {state.url}")
print(f"Title: {state.title}")
print(f"Tabs: {len(state.tabs)}")
```

#### `async def take_screenshot(full_page: bool = False) -> str | None`
Capture page screenshot as base64 string.

### Element Interaction

#### `async def get_element_by_index(index: int) -> ElementHandle | None`
Get element by its index from the DOM.

#### `async def wait_for_element(selector: str, timeout: int = 10000) -> None`
Wait for element to be visible.

## BrowserProfile Class

**Import:** `from browser_use import BrowserProfile`

Configuration class for browser settings.

```python
class BrowserProfile(BaseModel):
    channel: BrowserChannel = 'chrome'
    headless: bool = False
    user_data_dir: Path | None = None
    viewport: ViewportSize | None = None
    timeout: int = 30000
    keep_alive: bool = False
    downloads_path: str | None = None
    storage_state: dict | str | None = None
```

### Usage Example

```python
profile = BrowserProfile(
    headless=False,
    viewport={"width": 1920, "height": 1080},
    keep_alive=False
)

async with BrowserSession(browser_profile=profile) as browser:
    await browser.get_current_page()
```


# LLM Integration API

## Base Classes

### BaseChatModel Protocol

**Import:** `from browser_use.llm import BaseChatModel`

Core protocol that all chat models implement.

```python
class BaseChatModel(Protocol):
    model: str
    provider: str
    name: str
    
    async def ainvoke(
        self, 
        messages: list[BaseMessage], 
        output_format: type[T] | None = None
    ) -> ChatInvokeCompletion[T]
```

## Message Types

```python
from browser_use.llm import (
    BaseMessage, UserMessage, SystemMessage, AssistantMessage,
    ContentText, ContentImage
)
```

### UserMessage
```python
UserMessage(
    content: str | list[ContentPartTextParam | ContentPartImageParam],
    name: str | None = None,
    cache: bool = False  # For Anthropic caching
)
```

### SystemMessage
```python
SystemMessage(
    content: str | list[ContentPartTextParam],
    cache: bool = False
)
```

### Content Types
```python
ContentText(text: str)
ContentImage(image_url=ImageURL(
    url: str,  # URL or base64
    detail: Literal['auto', 'low', 'high'] = 'auto'
))
```

## Chat Model Classes

### ChatOpenAI

```python
from browser_use.llm import ChatOpenAI

model = ChatOpenAI(
    model: str,  # "gpt-4", "gpt-3.5-turbo", etc.
    temperature: float | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    max_retries: int = 10
)
```

### ChatAnthropic

```python
from browser_use.llm import ChatAnthropic

model = ChatAnthropic(
    model: str,  # "claude-3-5-sonnet-20241022", etc.
    max_tokens: int = 8192,
    temperature: float | None = None,
    api_key: str | None = None
)
```

### ChatGoogle

```python
from browser_use.llm import ChatGoogle

model = ChatGoogle(
    model: str,  # "gemini-2.0-flash", etc.
    temperature: float | None = None,
    api_key: str | None = None
)
```

### ChatGroq

```python
from browser_use.llm import ChatGroq

model = ChatGroq(
    model: str,
    temperature: float | None = None,
    api_key: str | None = None
)
```

### ChatOllama

```python
from browser_use.llm import ChatOllama

model = ChatOllama(
    model: str,  # Any Ollama model
    host: str | None = None,
    timeout: float | None = None
)
```

### ChatAzureOpenAI

```python
from browser_use.llm import ChatAzureOpenAI

model = ChatAzureOpenAI(
    model: str,
    api_key: str | None = None,
    api_version: str = '2024-10-21',
    azure_endpoint: str | None = None,
    azure_deployment: str | None = None
)
```

## Response Types

### ChatInvokeCompletion

```python
class ChatInvokeCompletion(BaseModel, Generic[T]):
    completion: T  # Response content
    thinking: str | None = None  # For reasoning models
    usage: ChatInvokeUsage | None = None
```

### ChatInvokeUsage

```python
class ChatInvokeUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cached_tokens: int | None = None
```

## Usage Examples

### Basic Text Generation

```python
from browser_use.llm import ChatOpenAI, UserMessage

model = ChatOpenAI(model="gpt-4")
messages = [UserMessage(content="Hello, how are you?")]

response = await model.ainvoke(messages)
print(response.completion)  # String response
print(response.usage.total_tokens)  # Token usage
```

### Structured Output

```python
from pydantic import BaseModel

class PersonInfo(BaseModel):
    name: str
    age: int

response = await model.ainvoke(messages, output_format=PersonInfo)
person = response.completion  # PersonInfo instance
```

### Multi-modal with Images

```python
from browser_use.llm import ContentText, ContentImage, ImageURL

messages = [UserMessage(content=[
    ContentText(text="What's in this image?"),
    ContentImage(image_url=ImageURL(
        url="https://example.com/image.jpg",
        detail="high"
    ))
])]

response = await model.ainvoke(messages)
```


# Controller and Actions API

## Controller Class

**Import:** `from browser_use import Controller`

Manages browser actions and provides a registry system for custom actions.

### Constructor

```python
class Controller(Generic[Context]):
    def __init__(
        self,
        exclude_actions: list[str] = [],
        output_model: type[T] | None = None,
        display_files_in_done_text: bool = True,
    )
```

### Main Methods

#### `async def act() -> ActionResult`
Execute a browser action.

```python
async def act(
    self,
    action: ActionModel,
    browser_session: BrowserSession,
    page_extraction_llm: BaseChatModel | None = None,
    sensitive_data: dict[str, str] | None = None,
    context: Context | None = None,
) -> ActionResult
```

#### `def action(description: str, **kwargs)`
Decorator for registering custom actions.

```python
controller = Controller()

@controller.action("Take a screenshot of the current page")
async def screenshot(browser_session: BrowserSession):
    page = browser_session.page
    await page.screenshot(path="screenshot.png")
    return {"success": True, "file": "screenshot.png"}
```

## Built-in Actions

The Controller includes these pre-registered actions:

### Navigation Actions
- **`go_to_url`** - Navigate to a URL
- **`go_back`** - Navigate back in browser history
- **`search_google`** - Search Google with a query

### Element Interaction
- **`click_element_by_index`** - Click an element by its index
- **`input_text`** - Input text into form fields
- **`upload_file`** - Upload files to file inputs
- **`scroll`** - Scroll pages or elements
- **`send_keys`** - Send keyboard keys

### Tab Management
- **`switch_tab`** - Switch between browser tabs
- **`close_tab`** - Close browser tabs

### Data Extraction
- **`extract_structured_data`** - Extract structured data from pages
- **`get_dropdown_options`** - Get dropdown menu options
- **`select_dropdown_option`** - Select dropdown options

### File Operations
- **`write_file`** - Write content to files
- **`read_file`** - Read file contents

### Utility Actions
- **`wait`** - Wait for specified seconds

## ActionModel

```python
class ActionModel(BaseModel):
    # Navigation
    go_to_url: dict[str, Any] | None = None
    go_back: dict[str, Any] | None = None
    search_google: dict[str, Any] | None = None
    
    # Interaction
    click_element_by_index: dict[str, Any] | None = None
    input_text: dict[str, Any] | None = None
    upload_file: dict[str, Any] | None = None
    
    # And more...
```

### Usage Example

```python
action = ActionModel(
    go_to_url={"url": "https://example.com"}
)
result = await controller.act(action, browser_session)
```

# DOM Service API

## DomService Class

**Import:** `from browser_use import DomService`

Handles DOM manipulation and element extraction.

### Constructor

```python
class DomService:
    def __init__(self, page: Page, logger: logging.Logger | None = None)
```

### Main Methods

#### `async def get_clickable_elements() -> DOMState`
Get all clickable elements from the current page.

```python
dom_state = await dom_service.get_clickable_elements(
    highlight_elements=True,
    focus_element=-1,
    viewport_expansion=0
)
```

**Returns:** `DOMState` object containing:
- `element_tree`: Hierarchical DOM structure
- `selector_map`: Mapping of indices to elements

#### `async def get_cross_origin_iframes() -> list[str]`
Get cross-origin iframe URLs.

## DOMState

```python
class DOMState(BaseModel):
    element_tree: DOMElementNode
    selector_map: SelectorMap
    clickable_elements_hashes: list[str] = []
```

### Usage Example

```python
dom_service = DomService(page)
dom_state = await dom_service.get_clickable_elements()

# Access elements
element_tree = dom_state.element_tree
selector_map = dom_state.selector_map
```


# Configuration and Utilities API

## Configuration

### Config Class

**Import:** `from browser_use.config import Config`

```python
config = Config()
# Access configuration properties
logging_level = config.BROWSER_USE_LOGGING_LEVEL
telemetry_enabled = config.ANONYMIZED_TELEMETRY
```

## Utility Functions

### SignalHandler

**Import:** `from browser_use.utils import SignalHandler`

Manages SIGINT (Ctrl+C) and SIGTERM signals in asyncio applications.

```python
class SignalHandler:
    def __init__(
        self,
        interruptible_tasks: list[str] = ['step', 'multi_act']
    )
    
    def register(self) -> None
    def unregister(self) -> None
    def wait_for_resume(self) -> None
    def reset(self) -> None
```

### Performance Decorators

```python
from browser_use.utils import time_execution_sync, time_execution_async

@time_execution_sync("Custom operation")
def sync_function():
    pass

@time_execution_async("Async operation")
async def async_function():
    pass
```

### URL Utilities

```python
from browser_use.utils import (
    match_url_with_domain_pattern,
    is_new_tab_page,
    is_unsafe_pattern
)

# Check URL patterns
matches = match_url_with_domain_pattern(
    "https://sub.example.com", 
    "*.example.com"
)  # Returns True

# Check for new tab pages
is_new = is_new_tab_page("chrome://newtab/")  # Returns True
```

## Custom Exceptions

**Import:** `from browser_use.exceptions import LLMException`

```python
class LLMException(Exception):
    def __init__(self, status_code, message):
        self.status_code = status_code
        self.message = message
```

# Complete Usage Examples

## Basic Agent Usage

```python
import asyncio
from browser_use import Agent
from browser_use.llm import ChatOpenAI

async def main():
    # Initialize agent
    agent = Agent(
        task="Go to Google and search for 'browser automation'",
        llm=ChatOpenAI(model="gpt-4"),
        use_vision=True,
        max_actions_per_step=5
    )
    
    # Run the agent
    history = await agent.run(max_steps=10)
    
    # Check results
    if history.is_successful():
        print("Task completed successfully!")
        print(f"Final result: {history.final_result()}")
    else:
        print("Task failed or incomplete")
        print(f"Errors: {history.errors()}")

asyncio.run(main())
```

## Advanced Agent with Custom Actions

```python
import asyncio
from browser_use import Agent, Controller, BrowserSession
from browser_use.llm import ChatOpenAI

async def main():
    # Create custom controller
    controller = Controller()
    
    # Register custom action
    @controller.action("Take a screenshot and save it")
    async def screenshot(browser_session: BrowserSession):
        page = await browser_session.get_current_page()
        await page.screenshot(path="screenshot.png")
        return {"success": True, "file": "screenshot.png"}
    
    # Initialize agent with custom controller
    agent = Agent(
        task="Navigate to example.com and take a screenshot",
        llm=ChatOpenAI(model="gpt-4"),
        controller=controller,
        save_conversation_path="./conversation.json",
        generate_gif=True
    )
    
    # Run with callbacks
    def on_step_start(agent_state):
        print(f"Starting step {agent_state.n_steps}")
    
    def on_step_end(agent_state):
        print(f"Completed step {agent_state.n_steps}")
    
    history = await agent.run(
        max_steps=20,
        on_step_start=on_step_start,
        on_step_end=on_step_end
    )
    
    # Save history
    agent.save_history("./agent_history.json")
    
    print(f"Total duration: {history.total_duration_seconds()} seconds")
    print(f"Number of steps: {len(history)}")

asyncio.run(main())
```

## Browser Session Management

```python
import asyncio
from browser_use import BrowserSession, BrowserProfile

async def main():
    # Configure browser
    profile = BrowserProfile(
        headless=False,
        viewport={"width": 1920, "height": 1080},
        keep_alive=False,
        downloads_path="./downloads"
    )
    
    # Use context manager for automatic cleanup
    async with BrowserSession(browser_profile=profile) as browser:
        # Get page state
        state = await browser.get_state_summary()
        print(f"Current URL: {state.url}")
        print(f"Page title: {state.title}")
        print(f"Number of tabs: {len(state.tabs)}")
        
        # Take screenshot
        screenshot = await browser.take_screenshot(full_page=True)
        
        # Get tab information
        tabs = await browser.get_tabs_info()
        for tab in tabs:
            print(f"Tab {tab.page_id}: {tab.title} - {tab.url}")
        
        # Switch between tabs if multiple exist
        if len(tabs) > 1:
            await browser.switch_to_tab(1)

asyncio.run(main())
```

## Multi-Modal LLM Usage

```python
import asyncio
from browser_use.llm import (
    ChatOpenAI, UserMessage, ContentText, ContentImage, ImageURL
)

async def main():
    model = ChatOpenAI(model="gpt-4-vision-preview")
    
    # Multi-modal message with text and image
    messages = [
        UserMessage(content=[
            ContentText(text="What's in this image?"),
            ContentImage(image_url=ImageURL(
                url="https://example.com/image.jpg",
                detail="high"
            ))
        ])
    ]
    
    response = await model.ainvoke(messages)
    print(response.completion)
    print(f"Tokens used: {response.usage.total_tokens}")

asyncio.run(main())
```

## Error Handling and Robustness

```python
import asyncio
from browser_use import Agent
from browser_use.llm import ChatOpenAI
from browser_use.llm.exceptions import ModelRateLimitError, ModelProviderError
from browser_use.utils import SignalHandler

async def main():
    # Set up signal handling
    signal_handler = SignalHandler(['step', 'multi_act'])
    signal_handler.register()
    
    try:
        agent = Agent(
            task="Complex web automation task",
            llm=ChatOpenAI(model="gpt-4"),
            max_failures=5,  # Allow more failures
            retry_delay=15,  # Longer retry delay
        )
        
        history = await agent.run(max_steps=50)
        
        if history.has_errors():
            print("Errors encountered:")
            for error in history.errors():
                if error:
                    print(f"- {error}")
        
    except ModelRateLimitError as e:
        print(f"Rate limited: {e}")
        # Implement backoff strategy
        
    except ModelProviderError as e:
        print(f"Provider error: {e}")
        # Handle provider-specific errors
        
    except KeyboardInterrupt:
        print("Task interrupted by user")
        
    finally:
        signal_handler.unregister()

asyncio.run(main())
```

# Environment Variables

Set these environment variables for LLM providers:

```bash
# OpenAI
OPENAI_API_KEY=sk-...

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Google
GOOGLE_API_KEY=AIza...

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://....openai.azure.com/
AZURE_OPENAI_KEY=...

# Groq
GROQ_API_KEY=gsk_...

# Other settings
BROWSER_USE_LOGGING_LEVEL=INFO
ANONYMIZED_TELEMETRY=true
```

# Dependencies

Core dependencies automatically installed:
- `playwright>=1.52.0` - Browser automation
- `pydantic>=2.11.5` - Data validation
- `httpx>=0.28.1` - HTTP client
- `aiofiles>=24.1.0` - Async file operations
- Provider-specific LLM clients (openai, anthropic, etc.)

Optional dependencies:
```bash
pip install "browser-use[cli]"     # CLI interface
pip install "browser-use[examples]" # Example dependencies
pip install "browser-use[all]"     # All optional dependencies
```

This comprehensive API documentation covers all major components of the browser-use library for AI-powered browser automation.
