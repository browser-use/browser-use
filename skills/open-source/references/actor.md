# Actor API (Legacy Direct Browser Control)

Low-level Playwright-like browser automation built on CDP. Use for precise, deterministic operations alongside the AI agent.

## Table of Contents
- [Architecture](#architecture)
- [Browser Methods](#browser-methods)
- [Page Methods](#page-methods)
- [Element Methods](#element-methods)
- [Mouse Methods](#mouse-methods)
- [Examples](#examples)

---

## Architecture

```
Browser (BrowserSession) → Page → Element
                                → Mouse
                                → AI Features (extract, find by prompt)
```

NOT Playwright — built on CDP with a subset of the Playwright API. Key differences:
- `get_elements_by_css_selector()` returns immediately (no visibility wait)
- Manual timing required after navigation
- `evaluate()` requires arrow function format: `() => {}`

## Browser Methods

```python
browser = Browser()
await browser.start()

page = await browser.new_page("https://example.com")  # Open new tab
pages = await browser.get_pages()                       # List all pages
current = await browser.get_current_page()              # Active page
await browser.close_page(page)                          # Close tab
await browser.stop()                                    # Cleanup
```

## Page Methods

### Navigation
- `goto(url: str)` — Navigate to URL
- `go_back()` — Back in history
- `go_forward()` — Forward in history
- `reload()` — Reload page

### Element Finding
- `get_elements_by_css_selector(selector: str) -> list[Element]` — Immediate return
- `get_element(backend_node_id: int) -> Element` — By CDP node ID
- `get_element_by_prompt(prompt: str, llm) -> Element | None` — LLM-powered
- `must_get_element_by_prompt(prompt: str, llm) -> Element` — Raises if not found

### JavaScript & Controls
- `evaluate(page_function: str, *args) -> str` — Execute JS (arrow function format)
- `press(key: str)` — Keyboard input
- `set_viewport_size(width: int, height: int)`
- `screenshot(format='jpeg', quality=None) -> str` — Base64 screenshot

### Information
- `get_url() -> str`
- `get_title() -> str`
- `mouse -> Mouse` — Mouse instance

### AI Features
- `extract_content(prompt: str, structured_output: type[T], llm) -> T` — LLM-powered extraction

## Element Methods

### Interactions
- `click(button='left', click_count=1, modifiers=None)`
- `fill(text: str, clear=True)` — Clear field and type
- `hover()`
- `focus()`
- `check()` — Toggle checkbox/radio
- `select_option(values: str | list[str])` — Select dropdown
- `drag_to(target: Element | Position)`

### Properties
- `get_attribute(name: str) -> str | None`
- `get_bounding_box() -> BoundingBox | None`
- `get_basic_info() -> ElementInfo`
- `screenshot(format='jpeg') -> str`

## Mouse Methods

```python
mouse = page.mouse
await mouse.click(x=100, y=200, button='left', click_count=1)
await mouse.move(x=500, y=600, steps=1)
await mouse.down(button='left')
await mouse.up(button='left')
await mouse.scroll(x=0, y=100, delta_x=None, delta_y=-500)
```

## Examples

### Mixed Agent + Actor

```python
async def main():
    llm = ChatOpenAI(api_key="your-key")
    browser = Browser()
    await browser.start()

    # Actor: precise navigation
    page = await browser.new_page("https://github.com/login")
    email = await page.must_get_element_by_prompt("username field", llm=llm)
    await email.fill("your-username")

    # Agent: AI-driven completion
    agent = Agent(browser=browser, llm=llm)
    await agent.run("Complete login and navigate to repositories")

    await browser.stop()
```

### JavaScript Execution

```python
title = await page.evaluate('() => document.title')
result = await page.evaluate('(x, y) => x + y', 10, 20)
stats = await page.evaluate('''() => ({
    url: location.href,
    links: document.querySelectorAll('a').length
})''')
```

### LLM-Powered Extraction

```python
from pydantic import BaseModel

class ProductInfo(BaseModel):
    name: str
    price: float

product = await page.extract_content("Extract product name and price", ProductInfo, llm=llm)
```

### Best Practices

- Use `asyncio.sleep()` after navigation-triggering actions
- Check URL/title changes to verify state transitions
- Implement retry logic for flaky elements
- Always call `browser.stop()` for cleanup
