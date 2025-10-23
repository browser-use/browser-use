# Gemini Computer Use Integration for Browser Use

This integration enables Google's Gemini 2.5 Computer Use model to control browsers using Browser Use's infrastructure while maintaining native Computer Use function calling.

## Architecture

### Core Components

1. **`chat.py`** - `ChatGeminiComputerUse` LLM Wrapper
   - Handles Google Gemini API communication
   - Configures Computer Use tools via `types.ComputerUse(environment='ENVIRONMENT_BROWSER')`
   - Serializes messages between Browser Use format and Gemini's `Content` format
   - Returns raw Gemini responses to allow function call detection

2. **`agent.py`** - `ComputerUseAgent` Orchestrator
   - Extends Browser Use's `Agent` class
   - Implements multi-turn function calling loop (up to 20 iterations per step)
   - Overrides `_get_next_action()` to handle Computer Use function calls
   - Overrides `_execute_actions()` to skip (actions already executed)
   - Uses custom system prompt that instructs pure function calling (no JSON output)

3. **`executor.py`** - `ComputerUseActionExecutor` Action Implementation
   - Executes all 13 Computer Use actions via Browser Use's Actor API
   - Denormalizes coordinates from 0-999 grid to actual pixels (1440x900)
   - Implements: `open_web_browser`, `navigate`, `click_at`, `type_text_at`, `scroll_document`, `get_browser_state`, `done`, etc.
   - Handles `open_web_browser` specially (returns `about:blank` on first call, skips duplicates)

4. **`bridge.py`** - `ComputerUseBridge` Adapter
   - Converts between Gemini function calls and Browser Use `ActionResult` format
   - Wraps executor results for agent consumption
   - Detects `done` action to signal completion

5. **`computer_use_system_prompt.md`** - Custom System Prompt
   - Instructs model to use ONLY function calling (no JSON structured output)
   - Explains Computer Use functions and workflow
   - Emphasizes calling `done(message="...")` when complete
   - Overrides Browser Use's default system prompt that requests JSON format

## How It Works

### Function Calling Loop

The integration uses a multi-turn conversation where the model calls functions and receives results:

```
Step 1 (Single Browser Use Agent Step):

  Iteration 1:
    → Model calls: open_web_browser()
    → Execute action, take screenshot (PNG)
    → Send function response with screenshot

  Iteration 2:
    → Model calls: navigate(url="https://news.ycombinator.com")
    → Execute action, take screenshot (PNG, resized if > 200KB)
    → Send function response with screenshot

  Iteration 3:
    → Model calls: get_browser_state()
    → Execute action, extract page text
    → Send function response

  Iteration 4:
    → Model calls: done(message="Top article: ...")
    → Detect done action
    → Exit loop with final result
```

### Key Differences from Base Agent

| Feature | Base Agent | ComputerUseAgent |
|---------|------------|------------------|
| LLM Calls | 1 call with structured output | Loop with function calling |
| System Prompt | Requests JSON format | Requests function calls only |
| Action Execution | After LLM in `_execute_actions()` | During LLM loop in `_get_next_action()` |
| Communication | Structured JSON output | Function calls + responses |
| Screenshots | Optional in browser state | Required in every function response |
| Action Format | Element-based (click index=5) | Coordinate-based (click_at x=500, y=300) |

### Critical Implementation Details

1. **System Prompt Override**
   - ComputerUseAgent overrides Browser Use's system prompt
   - Browser Use prompt asks for JSON: `{"thinking": "...", "action": [...]}`
   - Computer Use prompt asks for function calls only
   - This prevents the model from returning JSON instead of continuing function calls

2. **Screenshot Management**
   - Computer Use API requires PNG (not JPEG)
   - Screenshots are embedded in `FunctionResponse.parts` as `FunctionResponseBlob`
   - Large screenshots (> 200KB) are resized by 50% to avoid 503 errors
   - Each function response includes the current screenshot

3. **Message Format**
   - Gemini expects: user → assistant (function_call) → user (function_response) → ...
   - Must append assistant's message with function calls before function responses
   - Function responses are sent as `role='user'` messages
   - Each function call gets its own `FunctionResponse` part

4. **Coordinate Denormalization**
   ```python
   # Computer Use uses 0-999 normalized coordinates
   # Browser is 1440x900
   actual_x = int(normalized_x / 1000 * 1440)  # e.g., 500 → 720px
   actual_y = int(normalized_y / 1000 * 900)   # e.g., 500 → 450px
   ```

5. **open_web_browser Handling**
   - Model expects workflow: `open_web_browser()` → `navigate(url)`
   - First call: Navigate to `about:blank` and return `{'url': 'about:blank'}`
   - Subsequent calls: Skip navigation, still return `{'url': 'about:blank'}`
   - This matches the model's training (desktop Computer Use starts with empty browser)

## Supported Actions

All 13 Computer Use actions are implemented:

### Browser Control
- `open_web_browser()` - Opens browser (navigates to about:blank on first call)
- `navigate(url)` - Navigates to URL
- `go_back()` - Browser back button
- `go_forward()` - Browser forward button
- `search()` - Opens Google search page

### Mouse Actions
- `click_at(x, y)` - Click at normalized coordinates
- `hover_at(x, y)` - Hover at coordinates
- `drag_and_drop(x, y, destination_x, destination_y)` - Drag and drop

### Keyboard Actions
- `type_text_at(x, y, text, press_enter=True, clear_before_typing=True)` - Click field and type
- `key_combination(keys)` - Press key combo (e.g., "Control+C")

### Scrolling
- `scroll_document(direction)` - Scroll page (up/down/left/right)
- `scroll_at(x, y, direction, magnitude=800)` - Scroll at specific location

### Information & Control
- `get_browser_state()` - Get current URL and full page text
- `done(message)` - Mark task complete with summary
- `wait_5_seconds()` - Wait for page load

## Usage

```python
from browser_use.llm.gemini_computer_use import ChatGeminiComputerUse, ComputerUseAgent

# Initialize LLM with Computer Use enabled
llm = ChatGeminiComputerUse(
    model='gemini-2.5-computer-use-preview-10-2025',
    api_key='your-api-key',
    enable_computer_use=True,  # Required
)

# Create agent (automatically uses Computer Use system prompt)
agent = ComputerUseAgent(
    task='Find the top article on Hacker News and return its title',
    llm=llm,
    use_vision=True,  # Required for screenshots
    max_actions_per_step=20,  # Allow multiple function calls
)

# Run agent
result = await agent.run()

# Access the done message from the agent
final_message = result.final_result()  # Returns the done message text
print(f"Task result: {final_message}")

# If using output_model for structured extraction:
# structured_data = result.structured_output  # Returns parsed output_model
```

## Limitations & Notes

1. **Model Requirements**
   - MUST use `gemini-2.5-computer-use-preview-10-2025` or compatible model
   - `enable_computer_use=True` is required
   - Model enforces Computer Use tools - cannot disable them

2. **Screenshot Requirements**
   - Must be PNG format (JPEG not supported by API)
   - Large screenshots (> 200KB) are auto-resized to prevent timeouts
   - Screenshot required in every function response

3. **Function Calling Only**
   - Model cannot return structured JSON while using Computer Use
   - Uses function calling for all interactions
   - System prompt critical to prevent JSON output attempts

4. **Coordinate System**
   - All coordinates are 0-999 normalized
   - Browser resolution is fixed at 1440x900
   - Must manually convert visual positions to normalized coordinates

5. **Task Completion**
   - Model MUST call `done(message="...")` to finish
   - Without `done()`, agent will hit max iterations (20) and stop
   - The `done` action triggers loop exit and final result generation

## Troubleshooting

### Model returns JSON instead of function calls
- **Cause**: System prompt requesting JSON format
- **Fix**: ComputerUseAgent automatically overrides system prompt

### Model keeps calling open_web_browser in loop
- **Cause**: Returning current URL instead of about:blank
- **Fix**: Executor returns `about:blank` on first call, skips subsequent calls

### 503 errors with large screenshots
- **Cause**: PNG screenshots too large (> 500KB)
- **Fix**: Auto-resize screenshots > 200KB by 50%

### 400 error: "requires image of mime_type image/png"
- **Cause**: Using JPEG instead of PNG
- **Fix**: Always use PNG format, set `mime_type='image/png'`

### Model doesn't call done()
- **Cause**: System prompt not emphasizing completion
- **Fix**: Computer Use system prompt explicitly instructs calling `done()`

## Testing

```bash
# Run simple test
uv run python browser_use/llm/gemini_computer_use/test_simple.py

# Run full test with information extraction
uv run python browser_use/llm/gemini_computer_use/test_computer_use.py
```

## Architecture Comparison

### Standard Browser Use Flow
```
Agent: Request structured output
LLM: Returns {"action": [...]}
Agent: Execute actions via tools
Agent: Get new state
Agent: Repeat
```

### Computer Use Flow
```
Agent: Request function calls (no structure)
LLM: Returns function_call(name="click_at", args={x: 500, y: 300})
Agent: Execute via Actor API
Agent: Take screenshot
Agent: Send function_response(screenshot=...)
LLM: Returns next function_call OR done()
Agent: Repeat until done()
```

## File Reference

- `chat.py` - LLM wrapper (27KB, 747 lines)
- `agent.py` - Agent orchestrator (16KB, 426 lines)
- `executor.py` - Action implementations (7.5KB, 223 lines)
- `bridge.py` - Adapter layer (4.7KB, 171 lines)
- `computer_use_system_prompt.md` - Custom system prompt
- `test_simple.py` - Simple test example
- `test_computer_use.py` - Full test with extraction

## Credits

Implemented following Google's Computer Use API specification and Browser Use's architecture patterns.
