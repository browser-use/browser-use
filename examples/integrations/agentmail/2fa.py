import asyncio
import os
import sys

from agentmail import AsyncAgentMail  # type: ignore

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, Browser, models
from examples.integrations.agentmail.email_tools import EmailTools

TASK = """
Go to reddit.com, create a new account (use the get_email_address), make up password and all other information, confirm the 2fa with get_latest_email, and like latest post on r/elon subreddit.
"""


async def main():
	# Create email inbox
	# Get an API key from https://agentmail.to/
	email_client = AsyncAgentMail()
	inbox = await email_client.inboxes.create()
	print(f'Your email address is: {inbox.inbox_id}\n\n')

	# Initialize the tools for browser-use agent
	tools = EmailTools(email_client=email_client, inbox=inbox)

	# Initialize the LLM for browser-use agent
	llm = models.azure_gpt_4_1_mini

	# Set your local browser path
	browser = Browser(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

	agent = Agent(task=TASK, tools=tools, llm=llm, browser=browser)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
