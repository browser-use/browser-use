# Tools & Custom Actions

## Table of Contents
- [Quick Example](#quick-example)
- [Adding Custom Tools](#adding-custom-tools)
- [Injectable Parameters](#injectable-parameters)
- [Available Default Tools](#available-default-tools)
- [Removing Tools](#removing-tools)
- [Tool Response (ActionResult)](#tool-response)

---

## Quick Example

```python
from browser_use import Tools, ActionResult, BrowserSession

tools = Tools()

@tools.action('Ask human for help with a question')
async def ask_human(question: str, browser_session: BrowserSession) -> ActionResult:
    answer = input(f'{question} > ')
    return ActionResult(extracted_content=f'The human responded with: {answer}')

agent = Agent(task='Ask human for help', llm=llm, tools=tools)
```

> **Warning:** Parameter MUST be named `browser_session: BrowserSession`, not `browser: Browser`. Agent injects by name matching — wrong name fails silently.

## Adding Custom Tools

```python
@tools.action(description='Fill out banking forms', allowed_domains=['https://mybank.com'])
async def fill_bank_form(account_number: str) -> ActionResult:
    return ActionResult(extracted_content=f'Filled form for account {account_number}')
```

**Decorator parameters:**
- `description` (required): What the tool does — LLM uses this to decide when to call
- `allowed_domains`: Domains where tool can run (default: all)

### Pydantic Input

```python
from pydantic import BaseModel, Field

class Car(BaseModel):
    name: str = Field(description='Car name, e.g. "Toyota Camry"')
    price: int = Field(description='Price in USD')

@tools.action(description='Save cars to file')
def save_cars(cars: list[Car]) -> str:
    with open('cars.json', 'w') as f:
        json.dump([c.model_dump() for c in cars], f)
    return f'Saved {len(cars)} cars'
```

### Browser Interaction in Custom Tools

```python
@tools.action(description='Click submit button via CSS selector')
async def click_submit(browser_session: BrowserSession):
    page = await browser_session.must_get_current_page()
    elements = await page.get_elements_by_css_selector('button[type="submit"]')
    if not elements:
        return ActionResult(extracted_content='No submit button found')
    await elements[0].click()
    return ActionResult(extracted_content='Clicked!')
```

## Injectable Parameters

The agent fills function parameters by name. These special names are auto-injected:

| Parameter Name | Type | Description |
|---------------|------|-------------|
| `browser_session` | `BrowserSession` | Current browser session (CDP access) |
| `cdp_client` | | Direct Chrome DevTools Protocol client |
| `page_extraction_llm` | `BaseChatModel` | The LLM passed to agent |
| `file_system` | `FileSystem` | File system access |
| `available_file_paths` | `list[str]` | Files available for upload/processing |
| `has_sensitive_data` | `bool` | Whether action contains sensitive data |

### Page Methods (via browser_session)

```python
page = await browser_session.must_get_current_page()

# CSS selector
elements = await page.get_elements_by_css_selector('button.submit')

# LLM-powered (natural language)
element = await page.get_element_by_prompt("login button", llm=page_extraction_llm)
element = await page.must_get_element_by_prompt("login button", llm=page_extraction_llm)  # raises if not found
```

## Available Default Tools

Source: [tools/service.py](https://github.com/browser-use/browser-use/blob/main/browser_use/tools/service.py)

### Navigation & Browser Control
- `search` — Search queries (DuckDuckGo, Google, Bing)
- `navigate` — Navigate to URLs
- `go_back` — Go back in history
- `wait` — Wait for specified seconds

### Page Interaction
- `click` — Click elements by index
- `input` — Input text into form fields
- `upload_file` — Upload files
- `scroll` — Scroll page up/down
- `find_text` — Scroll to specific text
- `send_keys` — Send keys (Enter, Escape, Tab, etc.)

### JavaScript
- `evaluate` — Execute custom JS (shadow DOM, selectors, extraction)

### Tab Management
- `switch` — Switch between tabs
- `close` — Close tabs

### Content Extraction
- `extract` — Extract data using LLM

### Visual
- `screenshot` — Request screenshot in next browser state

### Form Controls
- `dropdown_options` — Get dropdown values
- `select_dropdown` — Select dropdown option

### File Operations
- `write_file` — Write to files
- `read_file` — Read files
- `replace_file` — Replace text in files

### Task Completion
- `done` — Complete the task (always available)

## Removing Tools

```python
tools = Tools(exclude_actions=['search', 'wait'])
agent = Agent(task='...', llm=llm, tools=tools)
```

## Tool Response

### Simple Return

```python
@tools.action('My tool')
def my_tool() -> str:
    return "Task completed successfully"
```

### ActionResult (Full Control)

```python
@tools.action('Advanced tool')
def advanced_tool() -> ActionResult:
    return ActionResult(
        extracted_content="Main result",
        long_term_memory="Remember this for all future steps",
        error="Something went wrong",
        is_done=True,
        success=True,
        attachments=["file.pdf"],
    )
```

### ActionResult Fields

| Field | Default | Description |
|-------|---------|-------------|
| `extracted_content` | None | Main result passed to LLM |
| `include_extracted_content_only_once` | False | Show large content only once, then drop |
| `long_term_memory` | None | Always included in LLM input for all future steps |
| `error` | None | Error message (auto-caught exceptions set this) |
| `is_done` | False | Tool completes entire task |
| `success` | None | Task success (only with `is_done=True`) |
| `attachments` | None | Files to show user |
| `metadata` | None | Debug/observability data |

### Context Control Strategy

1. **Short content, always visible**: Return string
2. **Long content shown once + persistent summary**: `extracted_content` + `include_extracted_content_only_once=True` + `long_term_memory`
3. **Never show, just remember**: Use `long_term_memory` alone
