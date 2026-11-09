"""Contract tests for the example; no browser, model call or external email traffic."""

import argparse
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

EXAMPLE = Path(__file__).resolve().parents[2] / 'examples/custom-functions/disposable_email_otp.py'
spec = importlib.util.spec_from_file_location('disposable_email_example', EXAMPLE)
assert spec is not None and spec.loader is not None
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)

# Fictional fixture values only, never a production inbox or credential.
ADDRESS = 'fixture@example.invalid'
TOKEN = 'synthetic-test-token'


def created():
	return httpx.Response(201, json={'success': True, 'inbox': {'address': ADDRESS, 'token': TOKEN}})


@pytest.mark.asyncio
async def test_real_registry_dispatch_retains_token_and_reads_both_fields():
	requests = []

	def handler(request):
		requests.append(request)
		assert request.headers['X-Gecici-Client'] == 'qa-test'
		if request.method == 'POST':
			assert 'authorization' not in request.headers
			return created()
		assert request.headers['Authorization'] == 'Bearer ' + TOKEN
		if request.url.path.endswith('/otp'):
			return httpx.Response(200, json={'success': True, 'otp': '123456'})
		if request.url.path.endswith('/links'):
			return httpx.Response(200, json={'success': True, 'verificationLink': 'https://example.invalid/verify'})
		return httpx.Response(200, json={'success': True})

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		inbox = example.InboxTools(client)
		tools = inbox.register()
		first = await tools.registry.execute_action('create_disposable_email', {})
		second = await tools.registry.execute_action('create_disposable_email', {})
		assert not first.error and first.extracted_content == second.extracted_content
		assert TOKEN not in first.model_dump_json()
		assert TOKEN not in inbox.inbox.model_dump_json()
		otp = await tools.registry.execute_action('wait_for_otp_code', {'timeout_seconds': 1})
		link = await tools.registry.execute_action('wait_for_confirmation_link', {'timeout_seconds': 1})
		assert json.loads(otp.extracted_content)['otp'] == '123456'
		assert json.loads(link.extracted_content)['verificationLink'] == 'https://example.invalid/verify'
		await inbox.close()
		assert inbox.inbox is None
		assert [r.method for r in requests] == ['POST', 'GET', 'GET', 'DELETE']


@pytest.mark.asyncio
async def test_delayed_email_pending_is_not_a_hard_error_and_same_inbox_can_retry():
	ready = False
	creates = 0

	def handler(request):
		nonlocal creates
		if request.method == 'POST':
			creates += 1
			return created()
		if ready:
			return httpx.Response(200, json={'success': True, 'otp': '123456'})
		return httpx.Response(408, json={'success': False, 'timeout': True})

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		inbox = example.InboxTools(client)
		tools = inbox.register()
		await tools.registry.execute_action('create_disposable_email', {})
		pending = await tools.registry.execute_action('wait_for_otp_code', {'timeout_seconds': 1})
		assert pending.error is None and not pending.is_done
		assert pending.success is not True
		assert json.loads(pending.extracted_content)['status'] == 'pending'
		ready = True
		received = await tools.registry.execute_action('wait_for_otp_code', {'timeout_seconds': 1})
		assert json.loads(received.extracted_content)['status'] == 'received'
		assert creates == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 404, 500, 302])
async def test_real_errors_are_masked_and_redirects_not_followed(status):
	seen = []

	def handler(request):
		seen.append(str(request.url))
		if request.method == 'POST':
			return created()
		return httpx.Response(status, headers={'Location': 'https://example.invalid/leak'}, text=TOKEN + ADDRESS)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
		inbox = example.InboxTools(client)
		await inbox.create()
		result = await inbox.wait('otp', 1)
		assert result.error
		assert TOKEN not in result.model_dump_json() and ADDRESS not in result.model_dump_json()
		assert len(seen) == 2 and all(url.startswith('https://gecici.email/api/v1/') for url in seen)


@pytest.mark.asyncio
async def test_cleanup_failure_keeps_token_for_retry():
	status = 500

	def handler(request):
		if request.method == 'POST':
			return created()
		return httpx.Response(status)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		inbox = example.InboxTools(client)
		await inbox.create()
		with pytest.raises(httpx.HTTPStatusError):
			await inbox.close()
		assert inbox.inbox is not None
		status = 404
		await inbox.close()
		assert inbox.inbox is None


@pytest.mark.parametrize('seconds', [0, 46, True])
def test_wait_bounds_are_in_the_tool_schema(seconds):
	with pytest.raises(ValueError):
		example.WaitParams(timeout_seconds=seconds)
	assert example.WaitParams().timeout_seconds == 45


@pytest.mark.parametrize('url', ['https://example.invalid/signup', 'http://localhost:8000/signup'])
def test_configurable_authorized_target(url):
	assert example.signup_url(url) == url


@pytest.mark.parametrize('url', ['example.invalid/signup', 'http://example.invalid/signup', 'https://user:pass@example.invalid'])
def test_invalid_targets_rejected_before_agent_starts(url):
	with pytest.raises(argparse.ArgumentTypeError):
		example.signup_url(url)
