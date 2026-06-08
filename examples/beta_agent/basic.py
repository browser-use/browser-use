"""Run the Rust-backed Browser Use Agent.

Set BROWSER_USE_TERMINAL_BINARY when the terminal binary is not on PATH.
Set BU_CDP_URL or BROWSER_USE_CDP_URL to attach to a remote Browser Use cloud browser.
Set BU_PROVIDER=openai or BU_PROVIDER=anthropic to choose a provider explicitly.
Set BU_MODEL to override the provider default.
"""

import asyncio
import os

from browser_use.beta import Agent, BrowserSession, ChatAnthropic, ChatOpenAI


def build_llm():
	provider = os.environ.get('BU_PROVIDER', '').strip().lower()
	if not provider:
		if os.environ.get('OPENAI_API_KEY'):
			provider = 'openai'
		elif os.environ.get('ANTHROPIC_API_KEY'):
			provider = 'anthropic'

	if provider == 'openai':
		return ChatOpenAI(model=os.environ.get('BU_MODEL', 'gpt-5-mini'))
	if provider == 'anthropic':
		return ChatAnthropic(model=os.environ.get('BU_MODEL', 'claude-sonnet-4-6'))

	raise RuntimeError('Set OPENAI_API_KEY or ANTHROPIC_API_KEY, or set BU_PROVIDER=openai|anthropic.')


async def main() -> None:
	cdp_url = os.environ.get('BU_CDP_URL') or os.environ.get('BROWSER_USE_CDP_URL')
	browser_session = BrowserSession(cdp_url=cdp_url) if cdp_url else None
	task = os.environ.get('BU_TASK', 'Open https://example.com and report the page title.')
	max_steps = int(os.environ.get('BU_MAX_STEPS', '20'))

	agent = Agent(
		task=task,
		llm=build_llm(),
		browser_session=browser_session,
	)
	history = await agent.run(max_steps=max_steps)
	print(history.final_result() or '(no final result)')


if __name__ == '__main__':
	asyncio.run(main())
