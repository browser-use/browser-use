"""Use a token-protected temporary inbox with an application you own or may test.

From this checkout: uv sync
Then: uv run examples/custom-functions/disposable_email_otp.py --signup-url YOUR_TEST_URL
Configure BROWSER_USE_API_KEY and the browser as in the repository quickstart. The URL
must serve a real registration form that sends a code or confirmation link.
No separate gecici-email package is required; httpx is a browser-use dependency.

Requests are labelled qa-test. This is receive-only email, not a delivery guarantee.
Only fictional test data belongs in this example: the model sees the address and
code/link, while the inbox token stays in Python. Review agent history settings.
"""

import argparse
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr

from browser_use import ActionResult, Agent, ChatBrowserUse, Tools

API_BASE_URL = 'https://gecici.email/api/v1'
MAX_PENDING_ATTEMPTS = 4  # Initial wait plus at most three retries, shared by both tools.
logger = logging.getLogger(__name__)


class Inbox(BaseModel):
	address: str = Field(min_length=1)
	token: SecretStr = Field(min_length=1, exclude=True)


class WaitParams(BaseModel):
	timeout_seconds: int = Field(default=45, ge=1, le=45, strict=True)


class InboxTools:
	"""One inbox per run; serialize calls and retain its token for authenticated cleanup."""

	def __init__(self, client: httpx.AsyncClient, *, api_base_url: str = API_BASE_URL):
		# Local HTTP tests exercise the real transport without accessing production.
		if api_base_url != API_BASE_URL:
			parsed = urlsplit(api_base_url)
			if (
				parsed.scheme != 'http'
				or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}
				or parsed.username
				or parsed.password
				or parsed.query
				or parsed.fragment
			):
				raise ValueError('API override must be a loopback HTTP URL without credentials, query or fragment.')
		self.api_base_url = api_base_url.rstrip('/')
		self.client = client
		self.inbox: Inbox | None = None
		self.lock = asyncio.Lock()
		self.pending_attempts = 0

	async def request(self, method: str, path: str, timeout: float = 10) -> httpx.Response:
		headers = {'Accept': 'application/json', 'X-Gecici-Client': 'qa-test'}
		if self.inbox:
			headers['Authorization'] = f'Bearer {self.inbox.token.get_secret_value()}'
		# Never forward an inbox token to a redirected endpoint.
		return await self.client.request(
			method,
			self.api_base_url + path,
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
					self.pending_attempts = 0
				return ActionResult(extracted_content=json.dumps({'status': 'created', 'address': self.inbox.address}))
			except Exception:
				return ActionResult(error='Could not create the test inbox. Check connectivity and API availability.')

	async def wait(self, kind: Literal['otp', 'links'], timeout_seconds: int = 45) -> ActionResult:
		async with self.lock:
			try:
				params = WaitParams(timeout_seconds=timeout_seconds)
				path = self.route() + '/' + kind
				if self.pending_attempts >= MAX_PENDING_ATTEMPTS:
					return self.delivery_timeout()
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
				self.pending_attempts += 1
				if self.pending_attempts >= MAX_PENDING_ATTEMPTS:
					return self.delivery_timeout()
				# An empty inbox is pending until the code-enforced retry budget is spent.
				return ActionResult(
					extracted_content=json.dumps(
						{
							'status': 'pending',
							'retries_remaining': MAX_PENDING_ATTEMPTS - self.pending_attempts,
							'next_step': 'No verification email yet. Retry on the same inbox within the remaining budget.',
						}
					)
				)
			except Exception:
				# Raw HTTP exception strings may contain inbox URLs or response contents.
				return ActionResult(error='Inbox read failed. Check creation, expiry, connectivity and timeout parameters.')

	def delivery_timeout(self) -> ActionResult:
		"""End an unsuccessful test when the per-inbox wait budget is exhausted."""
		return ActionResult(
			is_done=True,
			success=False,
			extracted_content=json.dumps(
				{
					'status': 'delivery_timeout',
					'retries_remaining': 0,
					'next_step': 'Stop this test: no verification email arrived within the allowed waits.',
				}
			),
		)

	async def close(self) -> None:
		async with self.lock:
			if self.inbox is not None:
				response = await self.request('DELETE', self.route())
				if response.status_code != 404:
					response.raise_for_status()
				self.inbox = None

	async def close_with_retry(self) -> None:
		"""Retry transient deletion failures at most twice; retain state on failure."""
		for attempt in range(3):
			try:
				await self.close()
				return
			except httpx.HTTPStatusError as error:
				status = error.response.status_code
				if attempt == 2 or (status != 429 and status < 500):
					raise
			except httpx.TransportError:
				if attempt == 2:
					raise
			await asyncio.sleep(0.25 * (attempt + 1))

	@asynccontextmanager
	async def cleanup_on_exit(self):
		"""Always attempt cleanup without replacing an exception from the agent."""
		try:
			yield
		except BaseException:
			try:
				await self.close_with_retry()
			except Exception:
				logger.warning('Test inbox cleanup failed; normal expiry still applies.')
			raise
		else:
			try:
				await self.close_with_retry()
			except Exception:
				raise RuntimeError('Test inbox cleanup failed; normal expiry still applies.') from None

	def register(self) -> Tools:
		tools = Tools()

		@tools.action('Create one temporary inbox for your authorized test. Returns its address; the token remains private.')
		async def create_disposable_email() -> ActionResult:
			return await self.create()

		@tools.action(
			'Wait up to 45 seconds for an OTP. Four empty waits across both tools end this run unsuccessfully.',
			param_model=WaitParams,
		)
		async def wait_for_otp_code(params: WaitParams) -> ActionResult:
			return await self.wait('otp', params.timeout_seconds)

		@tools.action(
			'Wait for a confirmation link without opening it. Shares the four-empty-wait budget with the OTP tool.',
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
		async with inbox.cleanup_on_exit():
			agent = Agent(task=task, llm=ChatBrowserUse(), tools=inbox.register())
			await agent.run()


if __name__ == '__main__':
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--signup-url', required=True, type=signup_url, help='Registration page of an application you may test')
	asyncio.run(main(parser.parse_args().signup_url))
