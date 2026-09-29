# Browser Use with the Anthropic SDK

Browser Use implements Anthropic's complete 31-action browser toolset. `Bash`
is a separate, bounded tool for local computation and deliverables. Both ship
from the main `browser-use` package.

## Quickstart

Install releases that include Browser Use's Anthropic integration and
Anthropic's browser toolset API:

```bash
pip install -U browser-use anthropic
export ANTHROPIC_API_KEY=...
export ANTHROPIC_MODEL=...
python examples/integrations/anthropic/quickstart.py
```

The integration composes as two peer tools:

```python
from anthropic import AsyncAnthropic
from browser_use.integrations.anthropic import Bash, BrowserUse

browser = BrowserUse()
bash = Bash(output_dir='outputs')

async with browser, AsyncAnthropic() as client:
	runner = client.beta.messages.tool_runner(
		model=model,
		tools=[browser, bash],
		messages=[{'role': 'user', 'content': task}],
	)
	result = await runner.until_done()
```

`BrowserUse()` creates, starts, and stops its own `BrowserSession`. To use an
existing session, pass it as `BrowserUse(session)`; the application keeps
responsibility for starting and stopping that session.

## Browser Use Cloud

Set `BROWSER_USE_API_KEY` and select Cloud directly on the driver:

```python
browser = BrowserUse(use_cloud=True)
bash = Bash(output_dir='outputs')

async with browser, AsyncAnthropic() as client:
	runner = client.beta.messages.tool_runner(
		model=model,
		tools=[browser, bash],
		messages=[{'role': 'user', 'content': task}],
	)
	result = await runner.until_done()
```

The driver creates the Cloud browser, connects over CDP, and stops the Cloud
browser when the context exits.

## Existing or remote browser

Pass any started `BrowserSession` to the driver. This is the same shape for an
existing local browser or a remote CDP endpoint:

```python
import os

from anthropic import AsyncAnthropic
from browser_use import BrowserSession
from browser_use.integrations.anthropic import Bash, BrowserUse

session = BrowserSession(cdp_url=os.environ['BROWSER_USE_CDP_URL'])
await session.start()
browser = BrowserUse(session)
bash = Bash(output_dir='outputs')

try:
	async with browser, AsyncAnthropic() as client:
		runner = client.beta.messages.tool_runner(
			model=model,
			tools=[browser, bash],
			messages=[{'role': 'user', 'content': task}],
		)
		result = await runner.until_done()
finally:
	await session.kill()
```

Bash still runs beside the SDK process, so files it creates are local to that
process. Remote uploads need a browser-host path or an application
`document_resolver`.

## Approval callback

The Anthropic SDK calls `confirm` before configured actions run. Keep
`javascript_exec` and `file_upload` disabled unless the application needs
them:

```python
async def confirm(context):
	return await app.approve(
		action=context.member,
		tab_id=context.tab_id,
		tab_url=context.tab_url,
	)


browser = BrowserUse(
	confirm=confirm,
	configs={'javascript_exec': {'enabled': True}},
)
```

## Browser actions

`BrowserUse` implements all browser-toolset members:

- Navigation and tabs: `navigate`, `new_tab`, `list_tabs`, `switch_tab`, `close_tab`
- Page state: `screenshot`, `zoom`, `read_page`, `find`, `get_page_text`, `wait`
- Pointer: `left_click`, `right_click`, `middle_click`, `double_click`,
  `triple_click`, `hover`, `mouse_move`, `left_mouse_down`, `left_mouse_up`,
  `left_click_drag`, `scroll`, `scroll_to`
- Input: `type`, `key`, `hold_key`, `form_input`, `file_upload`
- Diagnostics: `read_console`, `read_network`, `javascript_exec`

`file_upload` is disabled by default. Enable it only when upload paths are
already present on the browser host, or provide a `document_resolver` that maps
approved document IDs to browser-host paths. The adapter does not copy files
between the SDK host and a remote browser host.

`javascript_exec`, `read_console`, and `read_network` follow the Anthropic SDK's
tool configuration and confirmation policies. Enable only the members your
application needs, and pass the SDK's required `confirm` callback when enabling
members that can execute page code or expose diagnostic data.

## Bash behavior

`Bash(output_dir="outputs")` starts `/bin/bash` in the configured directory,
removes ambient credentials from the child environment, caps returned output,
enforces a timeout, and kills the entire process group on timeout. Configure
those bounds with `timeout_seconds` and `max_output_bytes`.

The working directory is not an operating-system sandbox. Bash still has the
permissions of the SDK process. Run the SDK process in your normal container or
sandbox when tasks may contain untrusted instructions.

## Anthropic SDK contract

Browser Use requires an Anthropic SDK release that publicly exports:

- `anthropic.tools.browser.BetaAsyncAbstractBrowserToolset20260801` and its
  result, state, error, policy, and input types
- `client.beta.messages.tool_runner(...)`
- mixed toolset and custom-tool execution, as used by `tools=[browser, bash]`

The SDK must also send the browser-tool beta header, serialize `browser_state`
for every member result, and preserve tool-result and compaction blocks across
long runs. Image size limits, context compaction, and cache reporting belong at
the SDK or API boundary because the adapter only returns individual screenshots.
