"""Built-in templates used when the remote template library is unavailable."""

CORE_INIT_TEMPLATES = {
	'default': {
		'file': 'default_template.py',
		'description': 'Simplest setup - capable of any web task with minimal configuration',
		'author': {
			'name': 'Reagan Hsu',
			'github_profile': 'https://github.com/Cheggin',
			'last_modified_date': '2025-11-11',
		},
	},
	'advanced': {
		'file': 'advanced_template.py',
		'description': 'All configuration options shown with defaults',
		'author': {
			'name': 'Reagan Hsu',
			'github_profile': 'https://github.com/Cheggin',
			'last_modified_date': '2025-11-11',
		},
	},
	'tools': {
		'file': 'tools_template.py',
		'description': 'Custom tool example - extend agent capabilities with your own functions',
		'author': {
			'name': 'Reagan Hsu',
			'github_profile': 'https://github.com/Cheggin',
			'last_modified_date': '2025-11-11',
		},
	},
}

CORE_INIT_TEMPLATE_CONTENTS = {
	'default_template.py': '''"""
Default browser-use example using ChatBrowserUse

The simplest way to use browser-use - capable of any web task
with minimal configuration.
"""

import asyncio

from dotenv import load_dotenv

from browser_use import Agent, Browser, ChatBrowserUse

load_dotenv()


async def main():
    browser = Browser(use_cloud=False)
    llm = ChatBrowserUse()
    task = "Find the number of stars of the browser-use repository on GitHub"
    agent = Agent(
        browser=browser,
        task=task,
        llm=llm,
    )
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
''',
	'advanced_template.py': '''"""
Advanced Example

This example demonstrates how to configure the Agent and Browser
with many configuration options, all set to default values.

Check out all configuration settings at https://docs.browser-use.com/customize/agent/all-parameters.
"""

import asyncio

from dotenv import load_dotenv

from browser_use import Agent, Browser, ChatBrowserUse

load_dotenv()


async def main():
    browser = Browser(
        use_cloud=False,
        # headless=False,
        # disable_security=False,
        # extra_chromium_args=[],
        # allowed_domains=None,
        # prohibited_domains=None,
        # cdp_url=None,
    )

    llm = ChatBrowserUse()

    agent = Agent(
        task="Find the number of stars of the browser-use repository on GitHub",
        llm=llm,
        browser=browser,
        # use_vision='auto',
        # save_conversation_path=None,
        # max_failures=3,
        # generate_gif=False,
        # max_actions_per_step=4,
        # use_thinking=True,
        # flash_mode=False,
        # calculate_cost=False,
        # step_timeout=180,
    )

    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
''',
	'tools_template.py': '''"""
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


@tools.registry.action("Save text content to a file")
async def save_to_file(filename: str, content: str):
    from pathlib import Path

    try:
        Path(filename).write_text(content, encoding="utf-8")
        return ActionResult(
            extracted_content=f"Saved to {filename}", include_in_memory=True
        )
    except Exception as e:
        return ActionResult(
            extracted_content=f"Error saving file: {e}", include_in_memory=True
        )


async def main():
    browser = Browser(use_cloud=False)
    llm = ChatBrowserUse()
    task = "Go to github.com and find the number of GitHub stars for browser-use and use the save_to_file tool to save the result to stars.txt"
    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        tools=tools,
    )

    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
''',
}
