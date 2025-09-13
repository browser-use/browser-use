# General CDP Tool

A new general-purpose tool has been added to browser-use that allows agents to execute arbitrary CDP actions using CSS selectors or XPath. This tool is designed to handle elements that are not detected as interactive by the standard DOM parsing but are actually clickable or interactable.

## Overview

The `execute_cdp_action` tool provides a unified interface for performing various browser actions using selectors instead of element indices. This is particularly useful when:

- Elements are not marked as interactive in the DOM state
- You need to interact with custom components or shadow DOM elements
- Standard tools fail to detect clickable elements
- You want to extract content from multiple elements at once
- You need to run custom JavaScript code

## Action Types

The tool supports the following action types:

### 1. Click (`action_type="click"`)
Click on elements using CSS selectors.
```python
GeneralCDPAction(
    action_type="click",
    selector="button.submit-btn",
    wait_for_selector=True,
    timeout=5.0
)
```

### 2. Type (`action_type="type"`)
Type text into input fields or contenteditable elements.
```python
GeneralCDPAction(
    action_type="type",
    selector="input[name='email']",
    text="user@example.com",
    wait_for_selector=True
)
```

### 3. Extract (`action_type="extract"`)
Extract content or attributes from elements.
```python
# Single element
GeneralCDPAction(
    action_type="extract",
    selector="h1.page-title",
    extract_attribute="textContent",
    multiple=False
)

# Multiple elements
GeneralCDPAction(
    action_type="extract",
    selector="div.product-card",
    extract_attribute="textContent",
    multiple=True
)
```

### 4. Evaluate (`action_type="evaluate"`)
Execute arbitrary JavaScript code.
```python
GeneralCDPAction(
    action_type="evaluate",
    selector="",  # Not needed for evaluate
    script="document.title"
)
```

### 5. Scroll To (`action_type="scroll_to"`)
Scroll to specific elements with optional offset.
```python
GeneralCDPAction(
    action_type="scroll_to",
    selector="#footer",
    scroll_offset=-100  # Scroll 100px above the element
)
```

### 6. Hover (`action_type="hover"`)
Hover over elements to trigger mouse events.
```python
GeneralCDPAction(
    action_type="hover",
    selector=".dropdown-trigger"
)
```

### 7. Select (`action_type="select"`)
Select options in dropdowns or select text in elements.
```python
GeneralCDPAction(
    action_type="select",
    selector="select[name='country']",
    text="United States"
)
```

## Parameters

- `action_type`: The type of action to perform (required)
- `selector`: CSS selector or XPath to target element(s) (required)
- `text`: Text to type or select (optional, required for type/select actions)
- `script`: JavaScript code to evaluate (optional, required for evaluate action)
- `extract_attribute`: Attribute to extract (optional, defaults to "textContent" for extract action)
- `multiple`: Whether to target multiple elements (optional, defaults to False)
- `scroll_offset`: Offset in pixels for scroll_to action (optional, defaults to 0)
- `wait_for_selector`: Whether to wait for selector to appear (optional, defaults to True)
- `timeout`: Timeout in seconds for waiting (optional, defaults to 5.0)

## Security Features

- All user inputs are properly escaped using `json.dumps()` to prevent JavaScript injection
- Selectors and text are safely embedded in JavaScript code
- Error handling provides clear feedback when selectors are not found

## Use Cases

1. **Clicking custom buttons**: Elements with custom click handlers that aren't detected as interactive
2. **Extracting structured data**: Get content from multiple similar elements at once
3. **Interacting with shadow DOM**: Use complex selectors to reach elements inside shadow roots
4. **Custom form interactions**: Type into non-standard input elements
5. **Dynamic content extraction**: Extract content that changes after interactions
6. **JavaScript execution**: Run custom scripts for complex interactions or data extraction

## Implementation Details

The tool is implemented in `browser_use/tools/service.py` and uses:
- Direct CDP (Chrome DevTools Protocol) calls via `Runtime.evaluate`
- JavaScript execution in the browser context
- Proper error handling and timeout management
- Safe string escaping to prevent injection attacks
- Consistent return format with metadata

## Files Modified

1. `browser_use/tools/views.py`: Added `GeneralCDPAction` Pydantic model
2. `browser_use/tools/service.py`: Added `execute_cdp_action` tool implementation

The tool integrates seamlessly with the existing browser-use architecture and follows the same patterns as other tools.