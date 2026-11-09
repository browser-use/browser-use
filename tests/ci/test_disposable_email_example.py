"""Real local HTTP contract tests; no remote mail, browser or model calls."""

import argparse
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Response

EXAMPLE = Path(__file__).resolve().parents[2] / 'examples/custom-functions/disposable_email_otp.py'
spec = importlib.util.spec_from_file_location('disposable_email_example', EXAMPLE)
assert spec is not None and spec.loader is not None
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)

# Fictional fixture values only, never a production inbox or credential.
ADDRESS = 'fixture@example.invalid'
TOKEN = 'synthetic-test-token'


def created():
	return Response(
		json.dumps({'success': True, 'inbox': {'address': ADDRESS, 'token': TOKEN}}), status=201, mimetype='application/json'
	)


def install_api(httpserver: HTTPServer, *, ready=True, read_status=200, delete_statuses=None):
	"""Serve the API over loopback; retain only synthetic test requests for assertions."""
	state = {'ready': ready, 'creates': 0, 'reads': 0, 'deletes': 0, 'seen': []}

	def handler(request):
		state['seen'].append(request)
		assert request.headers['X-Gecici-Client'] == 'qa-test'
		if request.method == 'POST':
			state['creates'] += 1
			assert 'Authorization' not in request.headers
			return created()
		assert request.headers['Authorization'] == 'Bearer ' + TOKEN
		if request.method == 'DELETE':
			statuses = delete_statuses or [200]
			status = statuses[min(state['deletes'], len(statuses) - 1)]
			state['deletes'] += 1
			return Response(status=status)
		state['reads'] += 1
		if read_status != 200:
			return Response(TOKEN + ADDRESS, status=read_status, headers={'Location': httpserver.url_for('/redirect-target')})
		if not state['ready']:
			return Response(json.dumps({'success': False, 'timeout': True}), status=408, mimetype='application/json')
		field = 'otp' if request.path.endswith('/otp') else 'verificationLink'
		value = '123456' if field == 'otp' else httpserver.url_for('/verify')
		return Response(json.dumps({'success': True, field: value}), mimetype='application/json')

	# These are local synthetic API routes. A redirect target is deliberately absent.
	for route, method in [
		('/inbox/generate', 'POST'),
		('/inbox/' + ADDRESS + '/otp', 'GET'),
		('/inbox/' + ADDRESS + '/links', 'GET'),
		('/inbox/' + ADDRESS, 'DELETE'),
	]:
		httpserver.expect_request('/api/v1' + route, method=method).respond_with_handler(handler)
	return state


async def test_real_registry_dispatch_retains_token_and_reads_both_fields(httpserver):
	state = install_api(httpserver)
	async with httpx.AsyncClient() as client:
		inbox = example.InboxTools(client, api_base_url=httpserver.url_for('/api/v1'))
		tools = inbox.register()
		first = await tools.registry.execute_action('create_disposable_email', {})
		second = await tools.registry.execute_action('create_disposable_email', {})
		assert not first.error and first.extracted_content == second.extracted_content
		assert TOKEN not in first.model_dump_json()
		assert TOKEN not in inbox.inbox.model_dump_json()
		otp = await tools.registry.execute_action('wait_for_otp_code', {'timeout_seconds': 1})
		link = await tools.registry.execute_action('wait_for_confirmation_link', {'timeout_seconds': 1})
		assert json.loads(otp.extracted_content)['otp'] == '123456'
		assert json.loads(link.extracted_content)['verificationLink'] == httpserver.url_for('/verify')
		await inbox.close()
		assert inbox.inbox is None
		assert [r.method for r in state['seen']] == ['POST', 'GET', 'GET', 'DELETE']
	httpserver.check_assertions()


async def test_delayed_email_pending_can_retry_same_inbox(httpserver):
	state = install_api(httpserver, ready=False)
	async with httpx.AsyncClient() as client:
		inbox = example.InboxTools(client, api_base_url=httpserver.url_for('/api/v1'))
		tools = inbox.register()
		await tools.registry.execute_action('create_disposable_email', {})
		pending = await tools.registry.execute_action('wait_for_otp_code', {'timeout_seconds': 1})
		assert pending.error is None and not pending.is_done and pending.success is not True
		assert json.loads(pending.extracted_content)['status'] == 'pending'
		assert json.loads(pending.extracted_content)['retries_remaining'] == 3
		state['ready'] = True
		received = await tools.registry.execute_action('wait_for_otp_code', {'timeout_seconds': 1})
		assert json.loads(received.extracted_content)['status'] == 'received'
		assert state['creates'] == 1


async def test_pending_budget_shared_by_tools_and_enforced_without_more_requests(httpserver):
	state = install_api(httpserver, ready=False)
	async with httpx.AsyncClient() as client:
		inbox = example.InboxTools(client, api_base_url=httpserver.url_for('/api/v1'))
		tools = inbox.register()
		await tools.registry.execute_action('create_disposable_email', {})
		for index in range(4):
			action = 'wait_for_otp_code' if index % 2 == 0 else 'wait_for_confirmation_link'
			result = await tools.registry.execute_action(action, {'timeout_seconds': 1})
			assert json.loads(result.extracted_content)['retries_remaining'] == 3 - index
		assert result.is_done and result.success is False
		assert json.loads(result.extracted_content)['status'] == 'delivery_timeout'
		reads = state['reads']
		await tools.registry.execute_action('create_disposable_email', {})
		again = await tools.registry.execute_action('wait_for_otp_code', {'timeout_seconds': 1})
		assert again.is_done and again.success is False
		assert state['reads'] == reads and state['creates'] == 1
		await inbox.close()
		await inbox.create()
		state['ready'] = True
		assert json.loads((await inbox.wait('otp', 1)).extracted_content)['status'] == 'received'


@pytest.mark.parametrize('status', [401, 403, 404, 500, 302])
async def test_errors_masked_and_redirects_not_followed(httpserver, status):
	state = install_api(httpserver, read_status=status)
	async with httpx.AsyncClient(follow_redirects=True) as client:
		inbox = example.InboxTools(client, api_base_url=httpserver.url_for('/api/v1'))
		await inbox.create()
		result = await inbox.wait('otp', 1)
		assert result.error
		assert TOKEN not in result.model_dump_json() and ADDRESS not in result.model_dump_json()
		assert len(state['seen']) == 2 and len(httpserver.log) == 2
	httpserver.check_assertions()


async def test_cleanup_failure_keeps_token_for_retry(httpserver):
	state = install_api(httpserver, delete_statuses=[500, 404])
	async with httpx.AsyncClient() as client:
		inbox = example.InboxTools(client, api_base_url=httpserver.url_for('/api/v1'))
		await inbox.create()
		with pytest.raises(httpx.HTTPStatusError):
			await inbox.close()
		assert inbox.inbox is not None
		await inbox.close()
		assert inbox.inbox is None and state['deletes'] == 2


async def test_runner_cleanup_retries_transient_failure(httpserver):
	state = install_api(httpserver, delete_statuses=[500, 503, 200])
	async with httpx.AsyncClient() as client:
		inbox = example.InboxTools(client, api_base_url=httpserver.url_for('/api/v1'))
		async with inbox.cleanup_on_exit():
			await inbox.create()
		assert state['deletes'] == 3 and inbox.inbox is None


@pytest.mark.parametrize('status,expected_attempts', [(500, 3), (403, 1)])
async def test_runner_cleanup_exhaustion_is_bounded_and_masked(httpserver, status, expected_attempts):
	state = install_api(httpserver, delete_statuses=[status])
	async with httpx.AsyncClient() as client:
		inbox = example.InboxTools(client, api_base_url=httpserver.url_for('/api/v1'))
		with pytest.raises(RuntimeError, match='cleanup failed') as failure:
			async with inbox.cleanup_on_exit():
				await inbox.create()
		assert state['deletes'] == expected_attempts and inbox.inbox is not None
		assert TOKEN not in str(failure.value) and ADDRESS not in str(failure.value)


async def test_runner_preserves_original_error_when_cleanup_also_fails(httpserver, caplog):
	state = install_api(httpserver, delete_statuses=[500])
	original = ValueError('Synthetic agent error')
	async with httpx.AsyncClient() as client:
		inbox = example.InboxTools(client, api_base_url=httpserver.url_for('/api/v1'))
		with pytest.raises(ValueError) as failure:
			async with inbox.cleanup_on_exit():
				await inbox.create()
				raise original
		assert failure.value is original
		assert state['deletes'] == 3 and inbox.inbox is not None
		messages = '\n'.join(record.getMessage() for record in caplog.records if record.name == example.__name__)
		assert 'cleanup failed' in messages
		assert TOKEN not in messages and ADDRESS not in messages


@pytest.mark.parametrize('seconds', [0, 46, True])
def test_wait_bounds_are_in_the_tool_schema(seconds):
	with pytest.raises(ValueError):
		example.WaitParams(timeout_seconds=seconds)
	assert example.WaitParams().timeout_seconds == 45


def test_configurable_authorized_target(httpserver):
	url = httpserver.url_for('/signup')
	assert example.signup_url(url) == url


@pytest.mark.parametrize('url', ['example.invalid/signup', 'http://example.invalid/signup', 'https://user:pass@example.invalid'])
def test_invalid_targets_rejected_before_agent_starts(url):
	with pytest.raises(argparse.ArgumentTypeError):
		example.signup_url(url)


@pytest.mark.parametrize(
	'url', ['https://example.invalid/api', 'http://localhost:8000/api?token=value', 'http://user:pass@localhost:8000/api']
)
async def test_api_override_limited_to_loopback_without_credentials_or_query(url):
	async with httpx.AsyncClient() as client:
		with pytest.raises(ValueError):
			example.InboxTools(client, api_base_url=url)
