"""
Example demonstrating log redaction for protecting sensitive data.

This example shows how to use the redact_logs parameter to automatically
redact sensitive information from all logger outputs.
"""

import asyncio

from browser_use import Agent, Browser, ChatBrowserUse


async def main():
	# Example 1: Agent with log redaction enabled
	# All sensitive data will be redacted from logs
	agent = Agent(
		task='Go to https://example.com and search for confidential information',
		llm=ChatBrowserUse(),
		browser=Browser(headless=True),
		redact_logs=True,  # Enable log redaction
	)

	# When logs are written, sensitive information will be replaced with:
	# - Task content: [REDACTED_TASK]
	# - URLs: [REDACTED_URL]
	# - CDP URLs: [REDACTED_CDP_URL]
	# - Action parameters (text, query, value, content): [REDACTED]

	# Run the agent
	history = await agent.run(max_steps=3)

	print('\n' + '=' * 80)
	print('With redact_logs=True, all sensitive data in logs is automatically redacted')
	print('=' * 80 + '\n')

	# Example 2: Normal logging (default behavior)
	agent_normal = Agent(
		task='Go to https://example.com and search for information',
		llm=ChatBrowserUse(),
		browser=Browser(headless=True),
		redact_logs=False,  # Default: no redaction
	)

	history_normal = await agent_normal.run(max_steps=3)

	print('\n' + '=' * 80)
	print('With redact_logs=False (default), logs show full details')
	print('=' * 80 + '\n')


if __name__ == '__main__':
	asyncio.run(main())
