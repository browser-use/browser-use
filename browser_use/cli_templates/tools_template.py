"""
Custom Tools Example

This example demonstrates how to create custom tools that the agent can use
alongside the built-in browser actions.
"""

import asyncio

from dotenv import load_dotenv

from browser_use import ActionResult, Agent, Browser, ChatBrowserUse, Tools

load_dotenv()

# Create a Tools instance to register custom actions
tools = Tools()


@tools.registry.action('Save text content to a file')
async def save_to_file(filename: str, content: str):
	from pathlib import Path

	try:
		Path(filename).write_text(content, encoding='utf-8')
		return ActionResult(extracted_content=f'Saved to {filename}', include_in_memory=True)
	except Exception as e:
		return ActionResult(extracted_content=f'Error saving file: {e}', include_in_memory=True)


async def main():
	browser = Browser(use_cloud=False)
	llm = ChatBrowserUse()
	task = 'Go to github.com and find the number of GitHub stars for browser-use and use the save_to_file tool to save the result to stars.txt'
	agent = Agent(
		task=task,
		llm=llm,
		browser=browser,
		tools=tools,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
