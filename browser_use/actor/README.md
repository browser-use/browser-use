# Browser Actor

Browser Actor is a web automation library built on CDP (Chrome DevTools Protocol) that provides low-level browser automation capabilities within the browser-use ecosystem.

## Usage

### Integrated with Browser (Recommended)
```python
from browser_use import Browser  # Alias for BrowserSession

# Create and start browser session
browser = Browser()
await browser.start()

# Create new tabs and navigate
page = await browser.new_page("https://example.com")
pages = await browser.get_pages()
current_page = await browser.get_current_page()
```

### Direct Page Access (Advanced)
```python
from browser_use.actor import Page, Element, Mouse

# Create page with existing browser session
page = Page(browser_session, target_id, session_id)
```

## Basic Operations

```python
# Tab Management
page = await browser.new_page()  # Create blank tab
page = await browser.new_page("https://example.com")  # Create tab with URL
pages = await browser.get_pages()  # Get all existing tabs
await browser.close_page(page)  # Close specific tab

# Navigation
await page.goto("https://example.com")
await page.go_back()
await page.go_forward()
await page.reload()
```

## Element Operations

```python
# Find elements by CSS selector
elements = await page.get_elements_by_css_selector("input[type='text']")
buttons = await page.get_elements_by_css_selector("button.submit")

# Get element by backend node ID
element = await page.get_element(backend_node_id=12345)

# AI-powered element finding (requires LLM)
element = await page.get_element_by_prompt("search button", llm=your_llm)
element = await page.must_get_element_by_prompt("login form", llm=your_llm)
```

> **Note**: `get_elements_by_css_selector` returns immediately without waiting for visibility.

## Element Interactions

```python
# Element actions
await element.click(button='left', click_count=1, modifiers=['Control'])
await element.fill("Hello World")  # Clears first, then types
await element.hover()
await element.focus()
await element.check()  # Toggle checkbox/radio
await element.select_option(["option1", "option2"])  # For dropdown/select
await element.drag_to(target_element)  # Drag and drop

# Element properties
value = await element.get_attribute("value")
box = await element.get_bounding_box()  # Returns BoundingBox or None
info = await element.get_basic_info()  # Comprehensive element info
screenshot_b64 = await element.screenshot(format='jpeg')
```

## Mouse Operations

```python
# Mouse operations
mouse = await page.mouse
await mouse.click(x=100, y=200, button='left', click_count=1)
await mouse.move(x=300, y=400, steps=1)
await mouse.down(button='left')  # Press button
await mouse.up(button='left')    # Release button
await mouse.scroll(x=0, y=100, delta_x=0, delta_y=-500)  # Scroll at coordinates
```

## Page Operations

```python
# JavaScript evaluation
result = await page.evaluate('() => document.title')  # Must use arrow function format
result = await page.evaluate('(x, y) => x + y', 10, 20)  # With arguments

# Keyboard input
await page.press("Control+A")  # Key combinations supported
await page.press("Escape")     # Single keys

# Page controls
await page.set_viewport_size(width=1920, height=1080)
page_screenshot = await page.screenshot()  # JPEG by default
page_png = await page.screenshot(format="png", quality=90)

# Page information
url = await page.get_url()
title = await page.get_title()
```

## AI-Powered Features

```python
# Content extraction using LLM
from pydantic import BaseModel

class ProductInfo(BaseModel):
    name: str
    price: float
    description: str

# Extract structured data from current page
products = await page.extract_content(
    "Find all products with their names, prices and descriptions",
    ProductInfo,
    llm=your_llm
)
```

## Core Classes

- **BrowserSession** (aliased as **Browser**): Main browser session manager with tab operations
- **Page**: Represents a single browser tab or iframe for page-level operations
- **Element**: Individual DOM element for interactions and property access
- **Mouse**: Mouse operations within a page (click, move, scroll)

## API Reference

### BrowserSession Methods (Tab Management)
- `start()` - Initialize and start the browser session
- `stop()` - Stop the browser session (keeps browser alive)
- `kill()` - Kill the browser process and reset all state
- `new_page(url=None)` → `Page` - Create blank tab or navigate to URL
- `get_pages()` → `list[Page]` - Get all available pages
- `get_current_page()` → `Page | None` - Get the currently focused page
- `close_page(page: Page | str)` - Close page by object or ID
- Session management and CDP client operations

### Page Methods (Page Operations)
- `get_elements_by_css_selector(selector: str)` → `list[Element]` - Find elements by CSS selector
- `get_element(backend_node_id: int)` → `Element` - Get element by backend node ID
- `get_element_by_prompt(prompt: str, llm)` → `Element | None` - AI-powered element finding
- `must_get_element_by_prompt(prompt: str, llm)` → `Element` - AI element finding (raises if not found)
- `extract_content(prompt: str, structured_output: type[T], llm)` → `T` - Extract structured data using LLM
- `goto(url: str)` - Navigate this page to URL
- `go_back()`, `go_forward()` - Navigate history (with error handling)
- `reload()` - Reload the current page
- `evaluate(page_function: str, *args)` → `str` - Execute JavaScript (MUST use (...args) => format)
- `press(key: str)` - Press key on page (supports "Control+A" format)
- `set_viewport_size(width: int, height: int)` - Set viewport dimensions
- `screenshot(format='jpeg', quality=None)` → `str` - Take page screenshot, return base64
- `get_url()` → `str`, `get_title()` → `str` - Get page information
- `mouse` → `Mouse` - Get mouse interface for this page

### Element Methods (DOM Interactions)
- `click(button='left', click_count=1, modifiers=None)` - Click element with advanced fallbacks
- `fill(text: str, clear=True)` - Fill input with text (clears first by default)
- `hover()` - Hover over element
- `focus()` - Focus the element
- `check()` - Toggle checkbox/radio button (clicks to change state)
- `select_option(values: str | list[str])` - Select dropdown options
- `drag_to(target_element: Element | Position, source_position=None, target_position=None)` - Drag to target element
- `get_attribute(name: str)` → `str | None` - Get attribute value
- `get_bounding_box()` → `BoundingBox | None` - Get element position/size
- `screenshot(format='jpeg', quality=None)` → `str` - Take element screenshot, return base64
- `get_basic_info()` → `ElementInfo` - Get comprehensive element information


### Mouse Methods (Coordinate-Based Operations)
- `click(x: int, y: int, button='left', click_count=1)` - Click at coordinates
- `move(x: int, y: int, steps=1)` - Move to coordinates
- `down(button='left', click_count=1)`, `up(button='left', click_count=1)` - Press/release button
- `scroll(x=0, y=0, delta_x=None, delta_y=None)` - Scroll page at coordinates

## Type Definitions

### Position
```python
class Position(TypedDict):
    x: float
    y: float
```

### BoundingBox
```python
class BoundingBox(TypedDict):
    x: float
    y: float
    width: float
    height: float
```

### ElementInfo
```python
class ElementInfo(TypedDict):
    backendNodeId: int          # CDP backend node ID
    nodeId: int | None          # CDP node ID
    nodeName: str               # HTML tag name (e.g., "DIV", "INPUT")
    nodeType: int               # DOM node type
    nodeValue: str | None       # Text content for text nodes
    attributes: dict[str, str]  # HTML attributes
    boundingBox: BoundingBox | None  # Element position and size
    error: str | None           # Error message if info retrieval failed
```

## Important Usage Notes

**This is browser-use actor, NOT Playwright or Selenium.** Only use the methods documented above.

### Critical JavaScript Rules
- `page.evaluate()` MUST use `(...args) => {}` arrow function format
- Always returns string (objects are JSON-stringified automatically)
- Use single quotes around the function: `page.evaluate('() => document.title')`
- For complex selectors in JS: `'() => document.querySelector("input[name=\\"email\\"]")'`

### Method Restrictions
- `get_elements_by_css_selector()` returns immediately (no automatic waiting)
- For dropdowns: use `element.select_option()`, NOT `element.fill()`
- Form submission: click submit button or use `page.press("Enter")`
- No methods like: `element.submit()`, `element.dispatch_event()`, `element.get_property()`

### Error Prevention
- Always verify page state changes with `page.get_url()`, `page.get_title()`
- Use `element.get_attribute()` to check element properties
- Validate CSS selectors before use
- Handle navigation timing with appropriate `asyncio.sleep()` calls

### AI Features
- `get_element_by_prompt()` and `extract_content()` require an LLM instance
- These methods use DOM analysis and structured output parsing
- Best for complex page understanding and data extraction tasks
