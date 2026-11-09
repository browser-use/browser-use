"""Use a token-protected temporary inbox with an application you own or may test.

From this checkout: uv sync
Then: uv run examples/custom-functions/disposable_email_otp.py --signup-url YOUR_TEST_URL
Configure OPENAI_API_KEY and the browser as in the repository quickstart. The URL
must serve a real registration form that sends a code or confirmation link.
No separate gecici-email package is required; httpx is a browser-use dependency.

Requests are labelled qa-test. This is receive-only email, not a delivery guarantee.
Only fictional test data belongs in this example: the model sees the address and
code/link, while the inbox token stays in Python. Review agent history settings.
"""

import argparse
import asyncio
import json
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr

from browser_use import ActionResult, Agent, ChatOpenAI, Tools


class Inbox(BaseModel):
	address: str = Field(min_length=1)
	token: SecretStr = Field(min_length=1, exclude=True)


class WaitParams(BaseModel):
	timeout_seconds: int = Field(default=45, ge=1, le=45, strict=True)


class InboxTools:
	"""One inbox per run; serialize calls and retain its token for authenticated cleanup."""

	def __init__(self, client: httpx.AsyncClient):
		self.client = client
		self.inbox: Inbox | None = None
		self.lock = asyncio.Lock()

	async def request(self, method: str, path: str, timeout: float = 10) -> httpx.Response:
		headers = {'Accept': 'application/json', 'X-Gecici-Client': 'qa-test'}
		if self.inbox:
			headers['Authorization'] = f'Bearer {self.inbox.token.get_secret_value()}'
		# Never forward an inbox token to a redirected endpoint.
		return await self.client.request(
			method,
			'https://gecici.email/api/v1' + path,
			headers=headers,
			json={} if method == 'POST' else None,
			timeout=timeout,
			follow_redirects=False,
		)

	def route(self) -> str:
		if self.inbox is None:
			raise ValueError('Create the test inbox first')
		return '/inbox/' + quote(self.inbox.address, safe='')

	async def create(self) -> ActionResult:
		async with self.lock:
			try:
				if self.inbox is None:
					response = await self.request('POST', '/inbox/generate')
					response.raise_for_status()
					self.inbox = Inbox.model_validate(response.json()['inbox'])
				return ActionResult(extracted_content=json.dumps({'status': 'created', 'address': self.inbox.address}))
			except Exception:
				return ActionResult(error='Could not create the test inbox. Check connectivity and API availability.')

	async def wait(self, kind: Literal['otp', 'links'], timeout_seconds: int = 45) -> ActionResult:
		async with self.lock:
			try:
				params = WaitParams(timeout_seconds=timeout_seconds)
				path = self.route() + '/' + kind
				field = 'otp' if kind == 'otp' else 'verificationLink'
				loop = asyncio.get_running_loop()
				deadline = loop.time() + params.timeout_seconds
				while (remaining := deadline - loop.time()) > 0:
					response = await self.request('GET', path, timeout=min(10, remaining))
					if response.status_code != 408:
						response.raise_for_status()
						value = response.json().get(field)
						if isinstance(value, str) and value:
							return ActionResult(extracted_content=json.dumps({'status': 'received', field: value}))
					await asyncio.sleep(min(2, max(0, deadline - loop.time())))
				# An empty inbox is pending, not a tool failure or successful verification.
				return ActionResult(
					extracted_content=json.dumps(
						{
							'status': 'pending',
							'next_step': 'No verification email yet. Retry this wait on the same inbox up to three times; then report delivery pending.',
						}
					)
				)
			except Exception:
				# Raw HTTP exception strings may contain inbox URLs or response contents.
				return ActionResult(error='Inbox read failed. Check creation, expiry, connectivity and timeout parameters.')

	async def close(self) -> None:
		async with self.lock:
			if self.inbox is not None:
				response = await self.request('DELETE', self.route())
				if response.status_code != 404:
					response.raise_for_status()
				self.inbox = None

	def register(self) -> Tools:
		tools = Tools()

		@tools.action('Create one temporary inbox for your authorized test. Returns its address; the token remains private.')
		async def create_disposable_email() -> ActionResult:
			return await self.create()

		@tools.action(
			"Wait up to 45 seconds for an OTP in this run's inbox. Pending means retry, not verification success.",
			param_model=WaitParams,
		)
		async def wait_for_otp_code(params: WaitParams) -> ActionResult:
			return await self.wait('otp', params.timeout_seconds)

		@tools.action(
			"Wait up to 45 seconds for a confirmation link in this run's inbox. Returns the link without opening it.",
			param_model=WaitParams,
		)
		async def wait_for_confirmation_link(params: WaitParams) -> ActionResult:
			return await self.wait('links', params.timeout_seconds)

		return tools


def signup_url(value: str) -> str:
	parsed = urlsplit(value)
	if parsed.username or parsed.password or not parsed.hostname:
		raise argparse.ArgumentTypeError('Provide a test application URL without embedded credentials.')
	if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1', '::1'}):
		raise argparse.ArgumentTypeError('Use HTTPS, or HTTP for your local test application.')
	return value


async def main(target: str) -> None:
	load_dotenv()
	async with httpx.AsyncClient() as client:
		inbox = InboxTools(client)
		task = (
			'Create a test inbox using create_disposable_email.\n'
			f'Open the authorized test application at {target} and register with that address and fictional test data.\n'
			'After submitting the form, wait for the code or confirmation link using the corresponding tool.\n'
			'If pending, retry on the same inbox up to three times. Never invent a code or report pending as success.\n'
			'Enter the code or follow the confirmation link only for this test application.\n'
			'Report success only when the application explicitly confirms verification; otherwise report what failed.'
		)
		try:
			agent = Agent(task=task, llm=ChatOpenAI(model='gpt-4.1-mini'), tools=inbox.register())
			await agent.run()
		finally:
			try:
				await inbox.close()
			except Exception:
				raise RuntimeError('Test inbox cleanup failed; its normal expiry still applies.') from None


if __name__ == '__main__':
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--signup-url', required=True, type=signup_url, help='Registration page of an application you may test')
	asyncio.run(main(parser.parse_args().signup_url))
