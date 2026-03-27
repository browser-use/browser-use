"""
Inkbox + Browser Use: SMS verification example.

Uses an existing agent identity (with a phone number already provisioned)
to sign up for sites that require SMS verification.

Note: Phone numbers cost money to provision and are limited to 3 per org,
so this example uses an existing identity rather than creating a new one.
Set up your identity and phone number in the Inkbox console first.

Usage:
    python -m examples.integrations.inkbox.sms_verify

Env vars:
    INKBOX_API_KEY          - Inkbox API key (https://inkbox.ai/console)
    INKBOX_AGENT_HANDLE     - Agent identity handle with a phone number
    BROWSER_USE_API_KEY     - Browser Use API key
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv

load_dotenv()

from inkbox import Inkbox  # type: ignore

from browser_use import Agent, ChatBrowserUse
from examples.integrations.inkbox.inkbox_tools import InkboxTools

TASK = """
Go to instagram.com and create a new account. Use get_phone_number when it
asks for phone verification, then use get_latest_text to retrieve the SMS
verification code.
"""


async def main():
	inkbox_client = Inkbox(api_key=os.environ['INKBOX_API_KEY'])

	identity = inkbox_client.get_identity(os.environ['INKBOX_AGENT_HANDLE'])
	print(f'Agent: {identity.agent_handle}')
	if identity.mailbox:
		print(f'Email: {identity.mailbox.email_address}')
	if identity.phone_number:
		print(f'Phone: {identity.phone_number.number}')
	else:
		print('Warning: This identity has no phone number. Provision one in the Inkbox console.')
	print()

	tools = InkboxTools(identity=identity, inkbox_client=inkbox_client)
	llm = ChatBrowserUse(model='bu-2-0')
	agent = Agent(task=TASK, tools=tools, llm=llm)

	try:
		await agent.run()
	finally:
		inkbox_client.close()


if __name__ == '__main__':
	asyncio.run(main())
