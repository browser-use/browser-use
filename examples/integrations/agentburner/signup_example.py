"""
Sign up for a service using a disposable email from Agent Burner.
No API key needed.

Usage:
    pip install browser-use httpx
    python signup_example.py
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from browser_use import Agent, Browser, ChatBrowserUse
from examples.integrations.agentburner.email_tools import EmailTools

TASK = """
1. Use create_inbox to get a disposable email address
2. Go to https://buttondown.com/register
3. Fill the signup form with username 'abtestbu2026', the email, and password 'TestPass123!'
4. Submit the form
5. Use list_emails to check for incoming mail (retry a few times if empty)
6. Use get_email with the email ID to read the full email
7. Find the confirmation URL in the response and navigate to it
8. Report what happened
"""


async def main():
	tools = EmailTools()
	llm = ChatBrowserUse(model='bu-2-0')
	browser = Browser()
	agent = Agent(task=TASK, tools=tools, llm=llm, browser=browser)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
