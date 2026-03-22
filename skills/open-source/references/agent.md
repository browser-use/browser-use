# Agent Configuration & Behavior

## Table of Contents
- [Basic Usage](#basic-usage)
- [All Parameters](#all-parameters)
- [Output Format](#output-format)
- [Structured Output](#structured-output)
- [Prompting Guide](#prompting-guide)
- [Lifecycle Hooks](#lifecycle-hooks)
- [Timeout Environment Variables](#timeout-environment-variables)

---

## Basic Usage

```python
from browser_use import Agent, ChatBrowserUse

agent = Agent(
    task="Search for latest news about AI",
    llm=ChatBrowserUse(),
)

async def main():
    history = await agent.run(max_steps=500)
```

- `task`: The task to automate
- `llm`: LLM instance (see `models.md`)
- `max_steps` (default: `500`): Maximum agent steps

## All Parameters

### Core Settings
- `tools`: Registry of tools the agent can call
- `skills` (or `skill_ids`): List of skill IDs to load (e.g., `['skill-uuid']` or `['*']` for all). Requires `BROWSER_USE_API_KEY`
- `browser`: Browser object for browser settings
- `output_model_schema`: Pydantic model class for structured output validation

### Vision & Processing
- `use_vision` (default: `True`): `True` always includes screenshots, `"auto"` includes screenshot tool but only uses vision when requested, `False` never
- `vision_detail_level` (default: `'auto'`): `'low'`, `'high'`, or `'auto'`
- `page_extraction_llm`: Separate LLM for page content extraction (default: same as `llm`)

### Fallback & Resilience
- `fallback_llm`: Backup LLM when primary fails. Primary exhausts its retry logic (5 attempts with exponential backoff) first. Triggers on: 429 (rate limit), 401 (auth), 402 (payment), 500/502/503/504 (server errors). Once switched, fallback is used for rest of run.

### Actions & Behavior
- `initial_actions`: Actions to run before main task without LLM
- `max_actions_per_step` (default: `5`): Max actions per step (e.g., fill 5 form fields at once)
- `max_failures` (default: `5`): Max retries for steps with errors
- `final_response_after_failure` (default: `True`): Force one final model call after max_failures
- `use_thinking` (default: `True`): Enable explicit reasoning steps
- `flash_mode` (default: `False`): Fast mode — skips evaluation, next goal, thinking; uses memory only. Overrides `use_thinking`

### System Messages
- `override_system_message`: Completely replace default system prompt
- `extend_system_message`: Add instructions to default system prompt

### File & Data Management
- `save_conversation_path`: Path to save conversation history
- `save_conversation_path_encoding` (default: `'utf-8'`)
- `available_file_paths`: File paths the agent can access
- `sensitive_data`: Dict of sensitive data (see `examples.md` for patterns)

### Visual Output
- `generate_gif` (default: `False`): Generate GIF of actions. Set to `True` or string path
- `include_attributes`: HTML attributes to include in page analysis

### Performance & Limits
- `max_history_items`: Max steps to keep in LLM memory (`None` = all)
- `llm_timeout` (default: auto-detected per model — Groq: 30s, Gemini: 75s, Gemini 3 Pro: 90s, o3/Claude/DeepSeek: 90s, others: 75s): Seconds for LLM calls
- `step_timeout` (default: `180`): Seconds for each step
- `directly_open_url` (default: `True`): Auto-open URLs detected in task

### Advanced
- `calculate_cost` (default: `False`): Track API costs (access via `history.usage`)
- `display_files_in_done_text` (default: `True`)

### Backwards Compatibility
- `controller` → alias for `tools`
- `browser_session` → alias for `browser`

---

## Output Format

`run()` returns an `AgentHistoryList`:

```python
history = await agent.run()

# Basic access
history.urls()                    # Visited URLs
history.screenshot_paths()        # Screenshot file paths
history.screenshots()             # Screenshots as base64
history.action_names()            # Executed action names
history.extracted_content()       # Extracted content from all actions
history.errors()                  # Errors (None for clean steps)
history.model_actions()           # All actions with parameters
history.model_outputs()           # All model outputs
history.last_action()             # Last action

# Analysis
history.final_result()            # Final extracted content (last step)
history.is_done()                 # Agent completed?
history.is_successful()           # Completed successfully? (None if not done)
history.has_errors()              # Any errors?
history.model_thoughts()          # Reasoning (AgentBrain objects)
history.action_results()          # All ActionResult objects
history.action_history()          # Truncated action history
history.number_of_steps()         # Step count
history.total_duration_seconds()  # Total duration

# Structured output
history.structured_output         # Parsed structured output (if output_model_schema set)
```

## Structured Output

Use `output_model_schema` with a Pydantic model:

```python
from pydantic import BaseModel

class SearchResult(BaseModel):
    title: str
    url: str

agent = Agent(task="...", llm=llm, output_model_schema=SearchResult)
history = await agent.run()
result = history.structured_output  # SearchResult instance
```

---

## Prompting Guide

### Be Specific

```python
# Good
task = """
1. Go to https://quotes.toscrape.com/
2. Use extract action with the query "first 3 quotes with their authors"
3. Save results to quotes.csv using write_file action
"""

# Bad
task = "Go to web and make money"
```

### Name Actions Directly

```python
task = """
1. Use search action to find "Python tutorials"
2. Use click to open first result in a new tab
3. Use scroll action to scroll down 2 pages
4. Use extract to extract the names of the first 5 items
"""
```

### Handle Interaction Problems via Keyboard

```python
task = """
If the submit button cannot be clicked:
1. Use send_keys action with "Tab Tab Enter"
2. Or use send_keys with "ArrowDown ArrowDown Enter"
"""
```

### Custom Actions Integration

```python
@tools.action("Get 2FA code from authenticator app")
async def get_2fa_code():
    pass

task = """
Login with 2FA:
1. Enter username/password
2. When prompted for 2FA, use get_2fa_code action
3. NEVER try to extract 2FA codes from the page manually
"""
```

### Error Recovery

```python
task = """
1. Go to openai.com to find their CEO
2. If navigation fails due to anti-bot protection:
   - Use google search to find the CEO
3. If page times out, use go_back and try alternative approach
"""
```

---

## Lifecycle Hooks

Two hooks available via `agent.run()`:

| Hook | When Called |
|------|------------|
| `on_step_start` | Before agent processes current state |
| `on_step_end` | After agent executes all actions for step |

```python
async def my_hook(agent: Agent):
    state = await agent.browser_session.get_browser_state_summary()
    print(f'Current URL: {state.url}')

await agent.run(on_step_start=my_hook, on_step_end=my_hook)
```

### Data Available in Hooks

Full access to Agent instance:

- `agent.task` — current task; `agent.add_new_task(...)` — queue new task
- `agent.tools` — Tools() object and Registry
  - `agent.tools.registry.execute_action('click', {'index': 123}, browser_session=agent.browser_session)`
- `agent.sensitive_data` — sensitive data dict (mutable)
- `agent.settings` — all config options
- `agent.llm` — direct LLM access
- `agent.state` — internal state (thoughts, outputs, actions)
- `agent.history` — execution history:
  - `.model_thoughts()`, `.model_outputs()`, `.model_actions()`
  - `.extracted_content()`, `.urls()`
- `agent.browser_session` — BrowserSession + CDP:
  - `.agent_focus_target_id` — current target ID
  - `.get_or_create_cdp_session()` — CDP session
  - `.get_tabs()`, `.get_current_page_url()`, `.get_current_page_title()`
- `agent.pause()` / `agent.resume()` — control execution

### Hook Example: CDP Access

```python
async def my_hook(agent: Agent):
    cdp_session = await agent.browser_session.get_or_create_cdp_session()
    doc = await cdp_session.cdp_client.send.DOM.getDocument(session_id=cdp_session.session_id)
    html = await cdp_session.cdp_client.send.DOM.getOuterHTML(
        params={'nodeId': doc['root']['nodeId']}, session_id=cdp_session.session_id
    )
```

**Tips:**
- Keep hooks efficient (same execution thread)
- Most use cases are better served by custom tools
- Increase `step_timeout` if hooks take long

---

## Timeout Environment Variables

Fine-tune timeouts via environment variables (values in seconds):

### Browser Actions
| Variable | Default |
|----------|---------|
| `TIMEOUT_NavigateToUrlEvent` | 30.0 |
| `TIMEOUT_ClickElementEvent` | 15.0 |
| `TIMEOUT_ClickCoordinateEvent` | 15.0 |
| `TIMEOUT_TypeTextEvent` | 60.0 |
| `TIMEOUT_ScrollEvent` | 8.0 |
| `TIMEOUT_ScrollToTextEvent` | 15.0 |
| `TIMEOUT_SendKeysEvent` | 60.0 |
| `TIMEOUT_UploadFileEvent` | 30.0 |
| `TIMEOUT_GetDropdownOptionsEvent` | 15.0 |
| `TIMEOUT_SelectDropdownOptionEvent` | 8.0 |
| `TIMEOUT_GoBackEvent` | 15.0 |
| `TIMEOUT_GoForwardEvent` | 15.0 |
| `TIMEOUT_RefreshEvent` | 15.0 |
| `TIMEOUT_WaitEvent` | 60.0 |
| `TIMEOUT_ScreenshotEvent` | 15.0 |
| `TIMEOUT_BrowserStateRequestEvent` | 30.0 |

### Browser Lifecycle
| Variable | Default |
|----------|---------|
| `TIMEOUT_BrowserStartEvent` | 30.0 |
| `TIMEOUT_BrowserStopEvent` | 45.0 |
| `TIMEOUT_BrowserLaunchEvent` | 30.0 |
| `TIMEOUT_BrowserKillEvent` | 30.0 |
| `TIMEOUT_BrowserConnectedEvent` | 30.0 |

### Tab Management
| Variable | Default |
|----------|---------|
| `TIMEOUT_SwitchTabEvent` | 10.0 |
| `TIMEOUT_CloseTabEvent` | 10.0 |
| `TIMEOUT_TabCreatedEvent` | 30.0 |
| `TIMEOUT_TabClosedEvent` | 10.0 |

### Storage & Downloads
| Variable | Default |
|----------|---------|
| `TIMEOUT_SaveStorageStateEvent` | 45.0 |
| `TIMEOUT_LoadStorageStateEvent` | 45.0 |
| `TIMEOUT_FileDownloadedEvent` | 30.0 |
