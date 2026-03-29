"""
Inkbox + Browser Use: Autonomous signup with 2FA and secure credential management.

Demonstrates the full identity lifecycle:
  1. Create a fresh agent identity with its own email.
  2. Sign up for a service (Reddit) using the agent's email.
  3. Store credentials securely in the Inkbox vault.
  4. Enable 2FA (authenticator app) — QR decode, TOTP storage.
  5. Log out and log back in using secure-fill tools that never
     expose passwords or TOTP codes to the LLM.

Usage:
    python -m examples.integrations.inkbox.sign_up_and_manage_totp

Env vars:
    INKBOX_API_KEY      - Inkbox API key (https://inkbox.ai/console)
    BROWSER_USE_API_KEY - Browser Use API key
    INKBOX_VAULT_KEY    - Vault key for credential storage (optional)
"""

import asyncio
import os
import sys
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv

load_dotenv()

from inkbox import Inkbox

from browser_use import Agent, ChatBrowserUse
from examples.integrations.inkbox.inkbox_tools import InkboxTools, setup_vault

TASK = """
Go make a Reddit account with your email address (make up a username and password).

IMPORTANT — keep secrets out of this conversation:
- After creating the account, immediately store the credentials using store_credential
  (secret_type "login", include username, password, email, and url).
- When setting up 2FA via authenticator app: use read_qr_code to extract the TOTP URI,
  then update_credential to add the totp URI to the stored credential.
- When you need to enter the TOTP code on Reddit, use fill_totp_code with the element
  INDEX of the input field — do NOT use get_totp_code and type the code manually.
- When logging back in, use fill_credential with element INDICES for the username and
  password fields — do NOT type credentials manually.
- fill_credential and fill_totp_code accept element indices (the same index numbers you
  see in the page state), NOT CSS selectors.
- If you dont see email, ask reddit to resent it.

Steps:
1. Sign up with your email, pick a username, set a password.
2. Store the credential in the vault via store_credential.
3. Go to Settings > Account > enable Two-factor authentication.
4. Use read_qr_code to decode the QR code, then update_credential with the totp URI.
5. Use fill_totp_code with the element index to enter the 2FA code and complete setup.
6. Log out.
7. Log back in using fill_credential (with element indices) and fill_totp_code for the 2FA code.
"""


async def main():
	# ── Step 1: Connect to Inkbox ────────────────────────────────────

	api_key = os.environ.get('INKBOX_API_KEY')
	if not api_key:
		api_key = input('Enter your Inkbox API key (get one at https://inkbox.ai/console): ').strip()
		if not api_key:
			print('No API key provided. Exiting.')
			return

	inkbox_client = Inkbox(api_key=api_key)

	# ── Step 2: Create a fresh agent identity with a mailbox ─────────
	#
	# Each run gets its own identity and email address so demos
	# don't collide. The handle is a random unique identifier.

	handle = f'bu-{uuid.uuid4().hex[:8]}'
	try:
		identity = inkbox_client.create_identity(handle, create_mailbox=True)
	except Exception as e:
		print(f'\nFailed to create identity: {e}')
		if '401' in str(e) or '403' in str(e):
			print('Check your API key at https://inkbox.ai/console')
		else:
			print('This may be a temporary server issue — try again in a moment.')
		return

	# ── Step 3: Set up and unlock the vault ──────────────────────────
	#
	# Creates a vault if one doesn't exist, then unlocks it.
	# See setup_vault() in inkbox_tools.py for the full logic.

	if not setup_vault(inkbox_client, vault_key=os.environ.get('INKBOX_VAULT_KEY')):
		return

	# ── Step 4: Wire up the agent ────────────────────────────────────
	#
	# InkboxTools registers all Inkbox actions (email, SMS, vault,
	# secure-fill, QR decode) as Browser Use tools the agent can call.
	# The agent uses ChatBrowserUse (bu-2-0) as its LLM backbone.

	tools = InkboxTools(identity=identity, inkbox_client=inkbox_client)
	llm = ChatBrowserUse(model='bu-2-0')
	agent = Agent(task=TASK, tools=tools, llm=llm, max_steps=100)

	# ── Step 5: Run the agent ────────────────────────────────────────

	try:
		await agent.run()
	finally:
		inkbox_client.close()


if __name__ == '__main__':
	asyncio.run(main())
