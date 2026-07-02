"""
Record a Browser Use run with BrowserTrace.

Setup:
1. Install BrowserTrace in your Browser Use environment:
   uv pip install "browsertrace[ui]"
2. Set BROWSER_USE_API_KEY or configure another Browser Use-supported LLM.
3. Run this file, then open the local BrowserTrace UI:
   uvx --from "browsertrace[ui]" browsertrace
"""

import asyncio
import importlib
from typing import Any

from dotenv import load_dotenv

from browser_use import Agent, ChatBrowserUse


def _load_browsertrace() -> tuple[Any, Any]:
	try:
		browsertrace = importlib.import_module('browsertrace')
		browser_use_integration = importlib.import_module('browsertrace.integrations.browser_use')
	except ImportError as exc:
		raise SystemExit('BrowserTrace is not installed. Run: uv pip install "browsertrace[ui]"') from exc

	return getattr(browsertrace, 'Tracer'), getattr(browser_use_integration, 'create_run_hooks')


async def main() -> None:
	load_dotenv()

	Tracer, create_run_hooks = _load_browsertrace()
	tracer = Tracer()
	hooks = create_run_hooks(tracer, name='browser-use BrowserTrace example')

	agent = Agent(
		task='Find the founders of browser-use and return their names.',
		llm=ChatBrowserUse(),
	)

	with hooks:
		history = await agent.run(
			on_step_start=hooks.on_step_start,
			on_step_end=hooks.on_step_end,
		)

	print(f'Final result: {history.final_result()}')
	print('BrowserTrace recorded the run locally.')
	print('Open the UI with: uvx --from "browsertrace[ui]" browsertrace')


if __name__ == '__main__':
	asyncio.run(main())
