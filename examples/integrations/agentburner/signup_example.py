"""
Sign up for a service using a disposable email from Agent Burner.
No API key needed. No pip install beyond browser-use + httpx.

Usage:
    pip install browser-use httpx
    python signup_example.py
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from browser_use import Agent, Browser, ChatBrowserUse
from examples.integrations.agentburner.email_tools import EmailTools

TASK = """
Go to todoist.com/users/showregister, create a new account:
1. Use create_email to get a disposable email address
2. Make up a password (at least 8 characters)
3. Sign up with the email and password
4. Use get_verification_email to get the verification code
5. Enter the verification code to complete signup
"""


async def main():
	tools = EmailTools()

	llm = ChatBrowserUse(model="bu-2-0")

	browser = Browser()

	agent = Agent(task=TASK, tools=tools, llm=llm, browser=browser)

	await agent.run()

	# Cleanup
	await tools.inbox_key and tools.delete_inbox()


if __name__ == "__main__":
	asyncio.run(main())
