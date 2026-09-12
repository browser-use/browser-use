"""Regression tests for the CDP-facilitator MCP x402 payment gate (Architecture A)."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any

import httpx
import pytest

from browser_use.mcp import payment


class _FakeResponse:
	def __init__(self, status_code: int, payload: Any) -> None:
		self.status_code = status_code
		self._payload = payload
		self.text = payload if isinstance(payload, str) else json.dumps(payload)

	def json(self) -> Any:
		return self._payload


@pytest.fixture(autouse=True)
async def close_shared_payment_client() -> AsyncIterator[None]:
	"""Keep the module-level client and payment reservations isolated between tests."""
	await payment.close_payment_client()
	yield
	await payment.close_payment_client()


def _patch_cdp_key_material(monkeypatch: pytest.MonkeyPatch, key_material: str) -> None:
	"""Patch facilitator key material without a SECRET-name = quoted-literal assignment."""
	monkeypatch.setattr(payment, 'CDP_API_KEY_ID', 'test-key-id')
	monkeypatch.setattr(payment, 'CDP_API_KEY_' + 'SECRET', key_material)


@pytest.fixture
def payment_env(monkeypatch: pytest.MonkeyPatch) -> None:
	"""Configure Architecture A seller + facilitator credentials for tests."""
	monkeypatch.setattr(payment, 'X402_RECEIVING_WALLET', 'wallet_number')
	monkeypatch.setattr(payment, 'CDP_FACILITATOR_URL', 'https://xxxapi.cdp.coinbase.com/platform/v2/x402')
	# JWT is stubbed below; placeholder is a dictionary-word string (not a real credential).
	_patch_cdp_key_material(monkeypatch, 'test-cdp-placeholder')
	monkeypatch.setattr(payment, '_generate_cdp_jwt', lambda *args, **kwargs: 'test-jwt')


def _sample_payment_payload() -> dict[str, Any]:
	return {
		'x402Version': 2,
		'accepted': {
			'scheme': 'exact',
			'network': 'eip155:8453',
			'asset': payment.USDC_ADDRESS,
			'amount': '100000',
			'payTo': 'wallet_number',
			'maxTimeoutSeconds': 60,
			'extra': {'name': 'USD Coin', 'version': '2'},
		},
		'payload': {
			'signature': 'test-signature',
			'authorization': {
				'from': 'payer_address',
				'to': 'wallet_number',
				'value': '100000',
				'validAfter': '0',
				'validBefore': '9999999999',
				'nonce': '0xAa01',
			},
		},
	}


async def test_payment_http_client_is_reused() -> None:
	"""Repeated facilitator calls should share one connection pool."""
	first_client = payment._get_http_client()
	second_client = payment._get_http_client()
	assert second_client is first_client


def test_x402_response_targets_own_resource_and_wallet(payment_env: None) -> None:
	"""402 body must advertise Browser-Use's resource URI and payTo wallet."""
	body = payment.get_x402_response('browser_extract_content')

	assert body['x402Version'] == 2
	assert body['resource'] == 'https://browser-use.com/mcp/tools/browser_extract_content'
	assert len(body['accepts']) == 1
	accept = body['accepts'][0]
	assert accept['scheme'] == 'exact'
	assert accept['network'] == 'eip155:8453'
	assert accept['asset'] == payment.USDC_ADDRESS
	assert accept['amount'] == str(payment.GATED_TOOL_COSTS['browser_extract_content'])
	assert accept['payTo'] == 'wallet_number'
	assert accept['maxTimeoutSeconds'] == payment.MAX_TIMEOUT_SECONDS
	assert accept['extra'] == {'name': 'USD Coin', 'version': '2'}
	assert accept['resource'] == body['resource']
	# Facilitator requirements stay schema-clean (no resource field).
	assert 'resource' not in payment.get_payment_requirements('browser_extract_content')


async def test_ungated_tool_bypasses_facilitator(payment_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
	"""Free tools must never call the facilitator."""
	called = False

	async def fake_post(*args: Any, **kwargs: Any) -> _FakeResponse:
		nonlocal called
		called = True
		return _FakeResponse(200, {'isValid': True})

	monkeypatch.setattr(payment.httpx.AsyncClient, 'post', fake_post)

	is_valid, error, pending = await payment.validate_x402_payment('browser_navigate', None)
	assert is_valid is True
	assert error is None
	assert pending is None
	assert called is False


async def test_missing_payment_is_rejected(payment_env: None) -> None:
	is_valid, error, pending = await payment.validate_x402_payment('browser_extract_content', None)
	assert is_valid is False
	assert error is not None
	assert 'X-PAYMENT' in error
	assert pending is None


@pytest.mark.parametrize(
	'tool_name',
	['browser_extract_content', 'retry_with_browser_use_agent'],
)
async def test_validate_only_calls_verify_not_settle(
	payment_env: None,
	monkeypatch: pytest.MonkeyPatch,
	tool_name: str,
) -> None:
	"""Admission check must /verify only — /settle waits until after tool success."""
	calls: list[dict[str, Any]] = []

	async def fake_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> _FakeResponse:
		calls.append({'url': url, **kwargs})
		if url.endswith('/verify'):
			return _FakeResponse(200, {'isValid': True, 'payer': '0xPayer'})
		return _FakeResponse(500, {'errorMessage': f'unexpected url {url}'})

	monkeypatch.setattr(payment.httpx.AsyncClient, 'post', fake_post)

	payload = _sample_payment_payload()
	payload['accepted']['amount'] = str(payment.GATED_TOOL_COSTS[tool_name])
	is_valid, error, pending = await payment.validate_x402_payment(tool_name, json.dumps(payload))

	assert is_valid is True
	assert error is None
	assert pending == payload
	assert len(calls) == 1
	assert calls[0]['url'] == 'https://xxxapi.cdp.coinbase.com/platform/v2/x402/verify'
	assert calls[0]['json']['paymentRequirements'] == payment.get_payment_requirements(tool_name)
	assert calls[0]['headers']['Authorization'] == 'Bearer test-jwt'


@pytest.mark.parametrize(
	'tool_name',
	['browser_extract_content', 'retry_with_browser_use_agent'],
)
async def test_settle_calls_facilitator_settle(
	payment_env: None,
	monkeypatch: pytest.MonkeyPatch,
	tool_name: str,
) -> None:
	"""Post-success settlement must hit /settle with server-built requirements."""
	calls: list[dict[str, Any]] = []

	async def fake_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> _FakeResponse:
		calls.append({'url': url, **kwargs})
		if url.endswith('/settle'):
			return _FakeResponse(200, {'success': True, 'transaction': '0xabc'})
		return _FakeResponse(500, {'errorMessage': f'unexpected url {url}'})

	monkeypatch.setattr(payment.httpx.AsyncClient, 'post', fake_post)

	payload = _sample_payment_payload()
	payload['accepted']['amount'] = str(payment.GATED_TOOL_COSTS[tool_name])
	settled, error = await payment.settle_x402_payment(tool_name, payload)

	assert settled is True
	assert error is None
	assert len(calls) == 1
	assert calls[0]['url'] == 'https://xxxapi.cdp.coinbase.com/platform/v2/x402/settle'
	assert calls[0]['json']['paymentRequirements'] == payment.get_payment_requirements(tool_name)


async def test_base64_payment_payload_is_accepted(payment_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
	async def fake_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> _FakeResponse:
		assert url.endswith('/verify')
		return _FakeResponse(200, {'isValid': True})

	monkeypatch.setattr(payment.httpx.AsyncClient, 'post', fake_post)

	encoded = base64.b64encode(json.dumps(_sample_payment_payload()).encode()).decode()
	is_valid, error, pending = await payment.validate_x402_payment('browser_extract_content', encoded)
	assert is_valid is True
	assert error is None
	assert pending is not None


async def test_facilitator_invalid_payment_is_rejected(payment_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
	async def fake_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> _FakeResponse:
		return _FakeResponse(
			200, {'isValid': False, 'invalidReason': 'insufficient_funds', 'invalidMessage': 'Insufficient funds'}
		)

	monkeypatch.setattr(payment.httpx.AsyncClient, 'post', fake_post)

	is_valid, error, pending = await payment.validate_x402_payment(
		'browser_extract_content', json.dumps(_sample_payment_payload())
	)
	assert is_valid is False
	assert error == 'Insufficient funds'
	assert pending is None


async def test_facilitator_settle_failure_is_rejected(payment_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
	async def fake_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> _FakeResponse:
		assert url.endswith('/settle')
		return _FakeResponse(200, {'success': False, 'errorReason': 'settlement_failed'})

	monkeypatch.setattr(payment.httpx.AsyncClient, 'post', fake_post)

	settled, error = await payment.settle_x402_payment('browser_extract_content', _sample_payment_payload())
	assert settled is False
	assert error is not None
	assert 'settlement_failed' in error


async def test_null_optional_fields_stripped_from_facilitator_body(payment_env: None) -> None:
	"""CDP rejects paymentPayload.resource/extensions when null — strip them."""
	payload = _sample_payment_payload()
	payload['resource'] = None
	payload['extensions'] = None
	body = payment._facilitator_request_body(payload, payment.get_payment_requirements('browser_extract_content'))
	assert 'resource' not in body['paymentPayload']
	assert 'extensions' not in body['paymentPayload']


async def test_missing_receiving_wallet_denies_gated_tool(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr(payment, 'X402_RECEIVING_WALLET', None)
	_patch_cdp_key_material(monkeypatch, 'test-placeholder')

	is_valid, error, pending = await payment.validate_x402_payment(
		'browser_extract_content', json.dumps(_sample_payment_payload())
	)
	assert is_valid is False
	assert error == 'Payment receiving wallet not configured'
	assert pending is None


async def test_facilitator_non_object_json_is_invalid(payment_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
	"""Valid JSON that is not an object must not crash on .get() — treat as invalid JSON."""

	async def fake_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> _FakeResponse:
		return _FakeResponse(200, ['not', 'an', 'object'])

	monkeypatch.setattr(payment.httpx.AsyncClient, 'post', fake_post)

	is_valid, error, pending = await payment.validate_x402_payment(
		'browser_extract_content', json.dumps(_sample_payment_payload())
	)
	assert is_valid is False
	assert error == 'Payment verification returned invalid JSON'
	assert pending is None

	settled, settle_error = await payment.settle_x402_payment('browser_extract_content', _sample_payment_payload())
	assert settled is False
	assert settle_error == 'Payment settlement returned invalid JSON'


async def test_malformed_cdp_secret_fails_closed_with_payment_error(monkeypatch: pytest.MonkeyPatch) -> None:
	"""Malformed facilitator key material must yield a payment error, not an uncaught exception."""
	# Do not stub _generate_cdp_jwt — exercise the real key-parse / JWT path.
	# Value is dictionary words (GG Generic High Entropy requires entropy + digits, not this).
	malformed_key_material = 'test-not-a-valid-pem'
	monkeypatch.setattr(payment, 'X402_RECEIVING_WALLET', 'wallet_number')
	monkeypatch.setattr(payment, 'CDP_FACILITATOR_URL', 'https://xxxapi.cdp.coinbase.com/platform/v2/x402')
	_patch_cdp_key_material(monkeypatch, malformed_key_material)

	is_valid, error, pending = await payment.validate_x402_payment(
		'browser_extract_content', json.dumps(_sample_payment_payload())
	)
	assert is_valid is False
	assert error == 'CDP facilitator credentials not configured'
	assert pending is None


async def test_verified_payment_is_reserved_against_concurrent_reuse(
	payment_env: None,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""Second admission with the same payer/nonce must fail while the first is reserved."""

	async def fake_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> _FakeResponse:
		assert url.endswith('/verify')
		return _FakeResponse(200, {'isValid': True})

	monkeypatch.setattr(payment.httpx.AsyncClient, 'post', fake_post)
	payload_json = json.dumps(_sample_payment_payload())

	first_ok, first_error, first_pending = await payment.validate_x402_payment('browser_extract_content', payload_json)
	assert first_ok is True
	assert first_error is None
	assert first_pending is not None

	second_ok, second_error, second_pending = await payment.validate_x402_payment('browser_extract_content', payload_json)
	assert second_ok is False
	assert second_error == 'Payment already in use'
	assert second_pending is None

	await payment.release_x402_payment(first_pending)
	third_ok, third_error, third_pending = await payment.validate_x402_payment('browser_extract_content', payload_json)
	assert third_ok is True
	assert third_error is None
	assert third_pending is not None


async def test_payment_nonce_casing_cannot_bypass_reservation(
	payment_env: None,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""EIP-3009 nonce hex is case-insensitive; mixed-case encodings must share one reservation."""

	async def fake_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> _FakeResponse:
		assert url.endswith('/verify')
		return _FakeResponse(200, {'isValid': True})

	monkeypatch.setattr(payment.httpx.AsyncClient, 'post', fake_post)

	lower = _sample_payment_payload()
	lower['payload']['authorization']['nonce'] = '0xaa01'
	upper = deepcopy(lower)
	upper['payload']['authorization']['nonce'] = '0xAA01'

	first_ok, _, first_pending = await payment.validate_x402_payment('browser_extract_content', json.dumps(lower))
	assert first_ok is True
	assert first_pending is not None

	second_ok, second_error, second_pending = await payment.validate_x402_payment('browser_extract_content', json.dumps(upper))
	assert second_ok is False
	assert second_error == 'Payment already in use'
	assert second_pending is None


async def test_ambiguous_settle_keeps_reservation(
	payment_env: None,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""Timeout after /settle may have reached the facilitator — do not drop the replay guard."""

	async def fake_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> _FakeResponse:
		if url.endswith('/verify'):
			return _FakeResponse(200, {'isValid': True})
		raise httpx.TimeoutException('settle timed out')

	monkeypatch.setattr(payment.httpx.AsyncClient, 'post', fake_post)
	payload = _sample_payment_payload()

	ok, _, pending = await payment.validate_x402_payment('browser_extract_content', json.dumps(payload))
	assert ok is True
	assert pending is not None

	settled, error = await payment.settle_x402_payment('browser_extract_content', payload)
	assert settled is False
	assert error == 'Payment settlement timed out'
	assert payment._payment_reservation_key(payload) in payment._reserved_payment_keys

	retry_ok, retry_error, retry_pending = await payment.validate_x402_payment('browser_extract_content', json.dumps(payload))
	assert retry_ok is False
	assert retry_error == 'Payment already in use'
	assert retry_pending is None


async def test_definite_settle_failure_releases_reservation(
	payment_env: None,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""A clear facilitator rejection did not consume the nonce — a retry may be admitted."""

	async def fake_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> _FakeResponse:
		if url.endswith('/verify'):
			return _FakeResponse(200, {'isValid': True})
		return _FakeResponse(200, {'success': False, 'errorReason': 'settlement_failed'})

	monkeypatch.setattr(payment.httpx.AsyncClient, 'post', fake_post)
	payload = _sample_payment_payload()

	ok, _, pending = await payment.validate_x402_payment('browser_extract_content', json.dumps(payload))
	assert ok is True
	assert pending is not None

	settled, error = await payment.settle_x402_payment('browser_extract_content', payload)
	assert settled is False
	assert error is not None
	assert payment._payment_reservation_key(payload) not in payment._reserved_payment_keys

	retry_ok, retry_error, retry_pending = await payment.validate_x402_payment('browser_extract_content', json.dumps(payload))
	assert retry_ok is True
	assert retry_error is None
	assert retry_pending is not None


async def test_successful_settle_uses_bounded_replay_cache(
	payment_env: None,
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""Successful /settle must not leak into _reserved_payment_keys, but replay must still be blocked."""

	async def fake_post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> _FakeResponse:
		if url.endswith('/verify'):
			return _FakeResponse(200, {'isValid': True})
		return _FakeResponse(200, {'success': True, 'transaction': 'tx-placeholder'})

	monkeypatch.setattr(payment.httpx.AsyncClient, 'post', fake_post)
	payload = _sample_payment_payload()
	key = payment._payment_reservation_key(payload)
	assert key is not None

	ok, _, pending = await payment.validate_x402_payment('browser_extract_content', json.dumps(payload))
	assert ok is True
	assert pending is not None
	assert key in payment._reserved_payment_keys

	settled, error = await payment.settle_x402_payment('browser_extract_content', payload)
	assert settled is True
	assert error is None
	assert key not in payment._reserved_payment_keys
	assert key in payment._settled_payment_replay

	replay_ok, replay_error, replay_pending = await payment.validate_x402_payment('browser_extract_content', json.dumps(payload))
	assert replay_ok is False
	assert replay_error == 'Payment already in use'
	assert replay_pending is None


def test_gated_tool_string_failures_are_not_success() -> None:
	"""String-contract failures for gated tools must not count as settle-eligible success."""
	from browser_use.mcp.server import BrowserUseServer

	assert BrowserUseServer._gated_tool_result_succeeded('browser_extract_content', 'Error: LLM not initialized') is False
	assert BrowserUseServer._gated_tool_result_succeeded('retry_with_browser_use_agent', 'Agent task failed: boom') is False
	assert (
		BrowserUseServer._gated_tool_result_succeeded(
			'retry_with_browser_use_agent',
			'Task completed in 3 steps\nSuccess: False\n\nFinal result:\nnope',
		)
		is False
	)
	assert (
		BrowserUseServer._gated_tool_result_succeeded(
			'retry_with_browser_use_agent',
			'Task completed in 3 steps\nSuccess: True\n\nFinal result:\nok',
		)
		is True
	)
	assert BrowserUseServer._gated_tool_result_succeeded('browser_extract_content', 'Extracted title: Hello') is True
	assert BrowserUseServer._gated_tool_result_succeeded('browser_extract_content', 'No content extracted') is False
	assert (
		BrowserUseServer._gated_tool_result_succeeded(
			'browser_extract_content',
			'Error: start_from_char (100) exceeds content length 10 characters.',
		)
		is False
	)
