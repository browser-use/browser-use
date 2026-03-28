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

from inkbox import Inkbox  # type: ignore

from browser_use import Agent, ChatBrowserUse
from examples.integrations.inkbox.inkbox_tools import InkboxTools

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

Steps:
1. Sign up with your email, pick a username, set a password.
2. Store the credential in the vault via store_credential.
3. Go to Settings > Account > enable Two-factor authentication.
4. Use read_qr_code to decode the QR code, then update_credential with the totp URI.
5. Use fill_totp_code with the element index to enter the 2FA code and complete setup.
6. Log out.
7. Log back in using fill_credential (with element indices) and fill_totp_code for the 2FA code.
"""

DEFAULT_VAULT_KEY = 'BU_INKBOX_DEMO_VAULT_MASTER_PASSWORD'


async def main():
	api_key = os.environ.get('INKBOX_API_KEY')
	if not api_key:
		api_key = input('Enter your Inkbox API key (get one at https://inkbox.ai/console): ').strip()
		if not api_key:
			print('No API key provided. Exiting.')
			return

	inkbox_client = Inkbox(api_key=api_key)

	# Create identity first (needed for org_id if vault doesn't exist yet)
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

	# Vault setup: check if vault exists, create if needed, then unlock
	vault_key = os.environ.get('INKBOX_VAULT_KEY')
	vault_exists = True
	try:
		inkbox_client.vault.info()
	except Exception:
		vault_exists = False

	if not vault_exists:
		vault_key = DEFAULT_VAULT_KEY
		print(f'No vault found — creating one with default key: "{DEFAULT_VAULT_KEY}"')
		try:
			result = inkbox_client.vault.initialize(vault_key)
			print(f'Vault created! Save these recovery codes somewhere safe:')
			for i, code in enumerate(result.recovery_codes, 1):
				print(f'  {i}. {code}')
		except Exception as e:
			print(f'\nFailed to create vault: {e}')
			return
	elif not vault_key:
		vault_key = input(f'Set Inkbox vault master key (press Enter for "{DEFAULT_VAULT_KEY}"): ').strip() or DEFAULT_VAULT_KEY

	try:
		inkbox_client.vault.unlock(vault_key)
	except Exception as e:
		print(f'\nFailed to unlock vault: {e}')
		print('Check that the vault key matches the one used to create it.')
		return

	tools = InkboxTools(identity=identity, inkbox_client=inkbox_client)
	llm = ChatBrowserUse(model='bu-2-0')
	agent = Agent(task=TASK, tools=tools, llm=llm, max_steps=100)

	try:
		await agent.run()
	finally:
		inkbox_client.close()


if __name__ == '__main__':
	asyncio.run(main())
