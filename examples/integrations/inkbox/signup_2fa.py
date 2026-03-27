"""
Inkbox + Browser Use: Sign up for a service using the agent's own email and credentials.

Each run creates a fresh agent identity with its own email address. If a vault
key is provided, the agent can also use stored credentials and TOTP codes.

Usage:
    python -m examples.integrations.inkbox.signup_2fa

Env vars:
    INKBOX_API_KEY          - Inkbox API key (https://inkbox.ai/console)
    BROWSER_USE_API_KEY     - Browser Use API key
    INKBOX_VAULT_KEY        - Vault key to unlock stored credentials (optional)
"""

import asyncio
import os
import sys
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv

load_dotenv()

from inkbox import Inkbox  # type: ignore

from browser_use import Agent, ChatBrowserUse
from examples.integrations.inkbox.inkbox_tools import InkboxTools

TASK = """
Go make an Instagram account with your email address (make up a handle) and
then setup 2FA via authenticator app. Log out, then log back in using 2FA.
"""


async def main():
	inkbox_client = Inkbox(api_key=os.environ['INKBOX_API_KEY'])

	# Unlock vault if key is provided (enables credential + TOTP tools)
	vault_key = os.environ.get('INKBOX_VAULT_KEY')
	if vault_key:
		inkbox_client.vault.unlock(vault_key)
		print('Vault unlocked')

	# Create a fresh identity with a mailbox for this run
	handle = f'bu-{uuid.uuid4().hex[:8]}'
	identity = inkbox_client.create_identity(handle)
	identity.create_mailbox()

	print(f'Agent: {identity.agent_handle}')
	print(f'Email: {identity.mailbox.email_address}\n')

	tools = InkboxTools(identity=identity, inkbox_client=inkbox_client)
	llm = ChatBrowserUse(model='bu-2-0')
	agent = Agent(task=TASK, tools=tools, llm=llm)

	try:
		await agent.run()
	finally:
		inkbox_client.close()


if __name__ == '__main__':
	asyncio.run(main())
