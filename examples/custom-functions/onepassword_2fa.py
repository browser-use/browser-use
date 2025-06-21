import asyncio
import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from onepassword.client import Client  # type: ignore  # pip install onepassword-sdk

from browser_use import ActionResult, Agent, Controller

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OP_SERVICE_ACCOUNT_TOKEN = os.getenv('OP_SERVICE_ACCOUNT_TOKEN')
OP_ITEM_ID = os.getenv('OP_ITEM_ID')  # Go to 1Password, right click on the item, click "Copy Secret Reference"


controller = Controller()


@controller.registry.action('Get 2FA code from 1Password for Google Account', domains=['*.google.com', 'google.com'])
async def get_1password_2fa() -> ActionResult:
	"""
	Custom action to retrieve 2FA/MFA code from 1Password using onepassword.client SDK.
	"""
	client = await Client.authenticate(
		# setup instructions: https://github.com/1Password/onepassword-sdk-python/#-get-started
		auth=OP_SERVICE_ACCOUNT_TOKEN,
		integration_name='Browser-Use',
		integration_version='v1.0.0',
	)

	mfa_code = await client.secrets.resolve(f'op://Private/{OP_ITEM_ID}/One-time passcode')

	return ActionResult(extracted_content=mfa_code)


async def main():
	# Example task using the 1Password 2FA action
	task = 'Go to account.google.com, enter username and password, then if prompted for 2FA code, get 2FA code from 1Password for and enter it'

	model = ChatOpenAI(model='gpt-4o')
	agent = Agent(task=task, llm=model, controller=controller)

	result = await agent.run()
	print(f'Task completed with result: {result}')


if __name__ == '__main__':
	asyncio.run(main())
