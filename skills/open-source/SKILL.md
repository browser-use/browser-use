---
name: open-source
description: >
  Reference for writing Python code against the browser-use 1.0 open-source library (Agent, Browser, Tools,
  models, sensitive data, results). Use it whenever the user writes code that imports from browser_use, asks about
  Agent or Browser options, supported models, custom tools, or migrating from browser-use 0.x. Do NOT use this for
  Cloud API/SDK usage or pricing (use the cloud skill), or for driving a browser through the CLI (use the
  browser-use skill).
allowed-tools: Read
---

# Browser Use 1.0 library

The agent writes Python in a persistent REPL with browser helpers and raw CDP (on Pydantic AI). The full list of
0.x options and what replaced them is MIGRATING.md in the repo; every 0.x option 1.0 dropped raises one
"was removed in browser-use 1.0" error naming the replacement, before any browser starts.

## Install and first agent

```bash
uv pip install 'browser-use==1.0.1'   # Python >= 3.11. Always pin with ==, never >=: releases move fast
browser-use login               # one Browser Use key: default model and cloud browser (or set BROWSER_USE_API_KEY)
browser-use install             # only for Browser('chromium') without an installed Chrome
```

```python
import asyncio
from browser_use import Agent

async def main():
    result = await Agent('Find the top story on Hacker News').run()
    print(result.final_result())

asyncio.run(main())
```

`Agent(task).run_sync()` works outside async code (not inside a running event loop). Defaults: model `bu-fast` on
the Browser Use gateway, browser `Browser()` = a Browser Use Cloud browser.

## Agent

```python
Agent(
    task,                        # non-empty str
    llm=None,                    # default ChatBrowserUse('bu-fast')
    browser=None,                # default Browser() (cloud)
    tools=None,                  # Tools() with custom actions
    output_model_schema=None,    # pydantic model, Literal, enum...: result.structured_output
    sensitive_data=None,         # {'name': 'value'} or {'https://site.com': {'name': 'value'}}
    extend_system_message=None,
    reasoning=None,              # 'low' | 'medium' | 'high'
    mode=None,                   # default: 'ultrafast' on bu-fast / bu-ultrafast, else 'default'; 'ultrafast' = accessibility-tree helpers
    workspace=None,              # the agent's files; default a temp dir
)
await agent.run(max_steps=100, timeout=1700)  # max_steps >= 1; timeout in seconds for the agent loop
agent.add_new_task('next task')                # the next run() continues the same conversation
```

The result: `final_result()`, `structured_output`, `status` (`completed` | `max_steps` | `timeout` | `error`),
`is_successful()` (the agent's own verdict), `error`, `partial` (last `checkpoint(..., partial=True)`), `usage`,
`cost_usd`, `messages` (the transcript), and the files in `agent.workspace` (downloads in `workspace/downloads`).

## Models

```python
from browser_use import ChatBrowserUse, ChatOpenAI, ChatAnthropic, ChatGoogle

ChatBrowserUse('bu-fast')                          # also 'bu-ultrafast', 'bu-smart'
ChatOpenAI('gpt-6-luna')                           # OPENAI_API_KEY; Responses API
ChatOpenAI('my-model', base_url='http://localhost:8000/v1', api_key='x')  # any OpenAI-compatible server
ChatAnthropic('claude-haiku-5-5')                  # ANTHROPIC_API_KEY
ChatGoogle('gemini-3.5-flash')                     # GOOGLE_API_KEY
Agent(task, llm='groq:llama-3.3-70b-versatile')    # any Pydantic AI model string (groq: pip install 'pydantic-ai-slim[groq]'), or a Pydantic AI Model
```

## Browser

```python
from browser_use import Browser

Browser()                                   # Browser Use Cloud (default): cloud_profile_id, cloud_proxy_country_code='us',
                                            #   cloud_timeout (minutes, 1-240), live_view, captcha_solver
Browser('chromium')                         # a fresh local Chrome/Chromium with a temp profile; headless, executable_path,
                                            #   user_data_dir (a dedicated profile kept between runs)
Browser('chrome')                           # the Chrome you have open (enable chrome://inspect/#remote-debugging)
Browser('chrome', profile='Work')           # a new Chrome on a temporary copy of your profile 'Work'
Browser(cdp_url='http://127.0.0.1:9222')    # any CDP endpoint
Browser(keep_alive=True)                    # run() leaves it running: await browser.stop()
Browser(allowed_domains=['example.com'])    # also prohibited_domains, block_ip_addresses (every mode)
```

Give each concurrent Agent its own `Browser()`; one running Agent per Browser.

## Custom tools

```python
from browser_use import Agent, Tools, ActionResult

tools = Tools()

@tools.action('Look up the internal price of a product')
def get_price(sku: str) -> str:
    return prices[sku]

Agent(task, tools=tools)
```

Actions get only the arguments the model passes (no injected browser or page). Returning
`ActionResult(extracted_content=...)` or any value works; an action that raises returns the error to the model.

## Sensitive data

```python
Agent(
    'Log in with my account',
    sensitive_data={'https://example.com': {'user': 'me@example.com', 'password': '...'}},
)
```

The model sees only the names and types values with `type_secret('password')` (only into a focused field on a
matching site); values become `<secret:name>` in its output and the result. It is redaction, not a sandbox:
MIGRATING.md "Trust model" lists exactly what is covered.
