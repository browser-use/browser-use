"""
x402 payment gate for expensive Browser-Use MCP tools (Architecture A).

Billing is CDP-facilitator-settled x402 to Browser-Use's own payTo/resource.
invinoveritas is not in the payment path.

Flow (pay-on-success):
1. Client calls a gated tool without payment → 402 with x402 v2 accepts[]
2. Client signs a USDC-on-Base payment for our resource URI and retries with X-PAYMENT
3. Server /verify's the payload via the CDP facilitator (admission only — no on-chain transfer)
4. Server atomically reserves (payer, nonce) so concurrent calls cannot reuse the payload
5. On valid payment, the gated tool runs
6. Only after the tool succeeds does the server /settle (on-chain transfer);
   string-level tool failures release the reservation and do not settle.
   Ambiguous /settle outcomes (timeout, 5xx) keep the reservation so a retry
   cannot re-run the gated tool; successful settles move the key into a bounded TTL replay cache.

Free (ungated) tools bypass this module entirely.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
import time
from collections import OrderedDict
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None

# In-process reservation of verified (payer, nonce) pairs so concurrent tool calls
# cannot reuse one verified payload before /settle completes.
_payment_reservation_lock = asyncio.Lock()
_reserved_payment_keys: set[str] = set()
# Bounded TTL cache of successfully settled keys so a long-lived process does not
# accumulate reservations forever, while still blocking replay until expiry.
SETTLED_REPLAY_TTL_SECONDS = int(os.getenv('X402_SETTLED_REPLAY_TTL_SECONDS', '3600'))
SETTLED_REPLAY_CACHE_MAX = int(os.getenv('X402_SETTLED_REPLAY_CACHE_MAX', '4096'))
_settled_payment_replay: OrderedDict[str, float] = OrderedDict()

SettleCertainty = Literal['success', 'failed', 'ambiguous']

# CDP facilitator (Coinbase Developer Platform)
CDP_FACILITATOR_URL = os.getenv('CDP_FACILITATOR_URL', 'https://api.cdp.coinbase.com/platform/v2/x402').rstrip('/')
CDP_API_KEY_ID = os.getenv('CDP_API_KEY_ID')
CDP_API_KEY_SECRET = os.getenv('CDP_API_KEY_SECRET')

# Seller configuration — payTo is Browser-Use's receiving wallet
X402_RECEIVING_WALLET = os.getenv('X402_RECEIVING_WALLET')
X402_RESOURCE_BASE_URL = os.getenv('X402_RESOURCE_BASE_URL', 'https://browser-use.com/mcp/tools').rstrip('/')

# x402 v2 / Base mainnet USDC
X402_VERSION = 2
BASE_USDC_NETWORK = 'eip155:8453'
USDC_ADDRESS = os.getenv('USDC_ADDRESS', '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913')
# Base mainnet USDC EIP-712 domain name is "USD Coin" (not "USDC").
USDC_EXTRA = {'name': 'USD Coin', 'version': '2'}
MAX_TIMEOUT_SECONDS = int(os.getenv('X402_MAX_TIMEOUT_SECONDS', '60'))

# Amounts in atomic USDC (1 USDC = 1e6)
GATED_TOOL_COSTS = {
	'retry_with_browser_use_agent': int(os.getenv('X402_AGENT_AMOUNT', '1000000')),  # 1 USDC
	'browser_extract_content': int(os.getenv('X402_EXTRACT_AMOUNT', '100000')),  # 0.1 USDC
}

GATED_TOOL_DESCRIPTIONS = {
	'retry_with_browser_use_agent': 'Browser-Use autonomous agent run (LLM + browser)',
	'browser_extract_content': 'Browser-Use LLM content extraction',
}


def _get_http_client() -> httpx.AsyncClient:
	"""Return the shared payment client, recreating it after shutdown if needed."""
	global _client
	if _client is None or _client.is_closed:
		_client = httpx.AsyncClient(timeout=30)
	return _client


async def close_payment_client() -> None:
	"""Close the shared payment client's connection pool during server shutdown."""
	global _client
	if _client is not None and not _client.is_closed:
		await _client.aclose()
	_client = None
	await clear_payment_reservations()


def _canonicalize_eip3009_nonce(nonce: str) -> str:
	"""Normalize EIP-3009 nonce hex so letter casing cannot split the same authorization."""
	stripped = nonce.strip().lower()
	if stripped.startswith('0x'):
		stripped = stripped[2:]
	if stripped and all(c in '0123456789abcdef' for c in stripped):
		return f'0x{stripped}'
	return nonce.strip().lower()


def _payment_reservation_key(payment_payload: dict[str, Any]) -> str | None:
	"""Stable key for a signed payment: payer address + canonical authorization nonce."""
	inner = payment_payload.get('payload')
	if not isinstance(inner, dict):
		return None
	auth = inner.get('authorization')
	if isinstance(auth, dict):
		payer = auth.get('from')
		nonce = auth.get('nonce')
	else:
		payer = inner.get('from')
		nonce = inner.get('nonce')
	if not isinstance(payer, str) or not payer or not isinstance(nonce, str) or not nonce:
		return None
	return f'{payer.lower()}:{_canonicalize_eip3009_nonce(nonce)}'


def _purge_settled_replay_unlocked() -> None:
	"""Drop expired and overflow settled-replay entries. Caller must hold the lock."""
	now = time.time()
	expired = [key for key, expires_at in _settled_payment_replay.items() if expires_at <= now]
	for key in expired:
		del _settled_payment_replay[key]
	while len(_settled_payment_replay) > SETTLED_REPLAY_CACHE_MAX:
		_settled_payment_replay.popitem(last=False)


async def reserve_x402_payment(payment_payload: dict[str, Any]) -> tuple[bool, str | None]:
	"""
	Atomically reserve a verified payment's (payer, nonce) until settle or release.

	Prevents two concurrent gated tool calls from sharing one verified payload.
	"""
	key = _payment_reservation_key(payment_payload)
	if key is None:
		return False, 'Payment payload missing payer or nonce'

	async with _payment_reservation_lock:
		_purge_settled_replay_unlocked()
		if key in _settled_payment_replay or key in _reserved_payment_keys:
			return False, 'Payment already in use'
		_reserved_payment_keys.add(key)
	return True, None


async def release_x402_payment(payment_payload: dict[str, Any]) -> None:
	"""Release a reservation after tool failure or a definite settle failure so a retry can proceed."""
	key = _payment_reservation_key(payment_payload)
	if key is None:
		return
	async with _payment_reservation_lock:
		_reserved_payment_keys.discard(key)


async def _complete_x402_payment(payment_payload: dict[str, Any]) -> None:
	"""Move a reserved key into the bounded settled-replay cache after successful /settle."""
	key = _payment_reservation_key(payment_payload)
	if key is None:
		return
	async with _payment_reservation_lock:
		_reserved_payment_keys.discard(key)
		_purge_settled_replay_unlocked()
		_settled_payment_replay[key] = time.time() + SETTLED_REPLAY_TTL_SECONDS
		_settled_payment_replay.move_to_end(key)
		while len(_settled_payment_replay) > SETTLED_REPLAY_CACHE_MAX:
			_settled_payment_replay.popitem(last=False)


async def clear_payment_reservations() -> None:
	"""Drop all in-process payment reservations and settled-replay entries (tests / shutdown)."""
	async with _payment_reservation_lock:
		_reserved_payment_keys.clear()
		_settled_payment_replay.clear()


def is_tool_gated(tool_name: str) -> bool:
	"""Return True when the MCP tool requires an x402 payment."""
	return tool_name in GATED_TOOL_COSTS


def get_resource_url(tool_name: str) -> str:
	"""Stable resource URI naming the Browser-Use work being paid for."""
	return f'{X402_RESOURCE_BASE_URL}/{tool_name}'


def get_payment_requirements(
	tool_name: str,
	receiving_wallet: str | None = None,
) -> dict[str, Any]:
	"""Build the x402 v2 paymentRequirements object for a gated tool."""
	pay_to = receiving_wallet if receiving_wallet is not None else X402_RECEIVING_WALLET
	amount = GATED_TOOL_COSTS.get(tool_name, 1_000_000)
	return {
		'scheme': 'exact',
		'network': BASE_USDC_NETWORK,
		'asset': USDC_ADDRESS,
		'amount': str(amount),
		'payTo': pay_to,
		'maxTimeoutSeconds': MAX_TIMEOUT_SECONDS,
		'extra': dict(USDC_EXTRA),
	}


def get_x402_response(
	tool_name: str,
	error_message: str = 'X-PAYMENT header required',
	receiving_wallet: str | None = None,
) -> dict[str, Any]:
	"""
	Generate the x402 Payment Required JSON body (no WWW-Authenticate header).

	accepts[].resource names the Browser-Use work being paid for. Facilitator
	verify/settle uses get_payment_requirements() without that field.
	"""
	requirements = get_payment_requirements(tool_name, receiving_wallet=receiving_wallet)
	resource_url = get_resource_url(tool_name)
	accept = {
		**requirements,
		'resource': resource_url,
		'description': GATED_TOOL_DESCRIPTIONS.get(tool_name, tool_name),
	}
	return {
		'x402Version': X402_VERSION,
		'resource': resource_url,
		'accepts': [accept],
		'error': error_message,
	}


def _parse_payment_payload(x_payment_header: str) -> dict[str, Any]:
	"""Parse X-PAYMENT as JSON or base64-encoded JSON payment payload."""
	raw = x_payment_header.strip()
	candidates = [raw]
	try:
		candidates.append(base64.b64decode(raw, validate=False).decode('utf-8'))
	except (ValueError, UnicodeDecodeError):
		pass

	for candidate in candidates:
		try:
			payload = json.loads(candidate)
		except json.JSONDecodeError:
			continue
		if isinstance(payload, dict):
			return payload

	raise ValueError('X-PAYMENT must be a JSON or base64-encoded x402 payment payload')


def _parse_private_key(key_data: str) -> ec.EllipticCurvePrivateKey | ed25519.Ed25519PrivateKey:
	"""Parse a CDP API key secret (PEM EC or base64 Ed25519)."""
	if '\\n' in key_data:
		key_data = key_data.replace('\\n', '\n')

	try:
		key = serialization.load_pem_private_key(key_data.encode(), password=None)
		if isinstance(key, ec.EllipticCurvePrivateKey):
			return key
	except Exception:
		pass

	try:
		decoded = base64.b64decode(key_data)
		if len(decoded) == 64:
			return ed25519.Ed25519PrivateKey.from_private_bytes(decoded[:32])
	except Exception:
		pass

	raise ValueError('CDP_API_KEY_SECRET must be a PEM EC key or base64 Ed25519 key')


def _generate_cdp_jwt(request_method: str, request_host: str, request_path: str) -> str:
	"""Generate a short-lived CDP Bearer JWT for facilitator verify/settle."""
	if not CDP_API_KEY_ID or not CDP_API_KEY_SECRET:
		raise ValueError('CDP_API_KEY_ID and CDP_API_KEY_SECRET are required')

	private_key = _parse_private_key(CDP_API_KEY_SECRET)
	if isinstance(private_key, ec.EllipticCurvePrivateKey):
		algorithm = 'ES256'
	elif isinstance(private_key, ed25519.Ed25519PrivateKey):
		algorithm = 'EdDSA'
	else:
		raise ValueError('Unsupported CDP API key type')

	now = int(time.time())
	headers = {
		'alg': algorithm,
		'kid': CDP_API_KEY_ID,
		'typ': 'JWT',
		'nonce': ''.join(random.choices('0123456789', k=16)),
	}
	claims = {
		'sub': CDP_API_KEY_ID,
		'iss': 'cdp',
		'nbf': now,
		'exp': now + 120,
		'uris': [f'{request_method.upper()} {request_host}{request_path}'],
	}
	return jwt.encode(claims, private_key, algorithm=algorithm, headers=headers)


def _facilitator_auth_headers(path: str) -> dict[str, str]:
	"""Build Authorization headers for a CDP facilitator request path.

	Raises:
		ValueError: If CDP credentials are set but JWT generation fails (malformed secret, etc.).
	"""
	headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
	if not CDP_API_KEY_ID or not CDP_API_KEY_SECRET:
		return headers

	parsed = urlparse(CDP_FACILITATOR_URL)
	host = parsed.netloc or 'api.cdp.coinbase.com'
	# CDP JWTs bind to the full platform path (e.g. /platform/v2/x402/verify).
	base_path = parsed.path.rstrip('/') or '/platform/v2/x402'
	request_path = f'{base_path}{path}'
	try:
		token = _generate_cdp_jwt('POST', host, request_path)
	except Exception as e:
		raise ValueError(f'CDP facilitator credentials invalid: {e}') from e
	headers['Authorization'] = f'Bearer {token}'
	return headers


def _decode_facilitator_json_object(response: httpx.Response) -> dict[str, Any] | None:
	"""Decode a facilitator response body as a JSON object, or None if invalid."""
	try:
		data = response.json()
	except (json.JSONDecodeError, ValueError, TypeError):
		return None
	if not isinstance(data, dict):
		return None
	return data


def _facilitator_request_body(
	payment_payload: dict[str, Any],
	payment_requirements: dict[str, Any],
) -> dict[str, Any]:
	"""Build the CDP facilitator verify/settle JSON body."""
	# Drop null optional fields — CDP rejects resource/extensions: null on paymentPayload.
	cleaned_payload = {k: v for k, v in payment_payload.items() if v is not None}
	return {
		'x402Version': cleaned_payload.get('x402Version', X402_VERSION),
		'paymentPayload': cleaned_payload,
		'paymentRequirements': payment_requirements,
	}


async def validate_x402_payment(
	tool_name: str,
	x_payment_header: str | None,
) -> tuple[bool, str | None, dict[str, Any] | None]:
	"""
	Verify an x402 payment via the CDP facilitator (admission only).

	Does not call /settle — settlement happens after the tool succeeds so a failed
	agent/extract run does not charge the payer.

	Returns:
		(True, None, payment_payload) when payment is valid and the tool may run
		(False, error, None) when payment is missing/invalid — caller should return 402
		(True, None, None) when the tool is not gated
	"""
	if not is_tool_gated(tool_name):
		return True, None, None

	if not x_payment_header:
		return False, 'X-PAYMENT header required (x402 payment payload)', None

	if not X402_RECEIVING_WALLET:
		logger.warning('X402 gating enabled but X402_RECEIVING_WALLET is not set')
		return False, 'Payment receiving wallet not configured', None

	# CDP hosted facilitator requires API credentials; other facilitators may not.
	if 'api.cdp.coinbase.com' in CDP_FACILITATOR_URL and (not CDP_API_KEY_ID or not CDP_API_KEY_SECRET):
		logger.warning('X402 gating enabled but CDP API credentials are not set')
		return False, 'CDP facilitator credentials not configured', None

	try:
		payment_payload = _parse_payment_payload(x_payment_header)
	except ValueError as e:
		return False, str(e), None

	requirements = get_payment_requirements(tool_name)
	if not requirements.get('payTo'):
		return False, 'Payment receiving wallet not configured', None

	ok, error = await _verify_with_facilitator(tool_name, payment_payload, requirements)
	if not ok:
		return False, error, None

	reserved, reserve_error = await reserve_x402_payment(payment_payload)
	if not reserved:
		return False, reserve_error or 'Payment already in use', None

	return True, None, payment_payload


async def settle_x402_payment(
	tool_name: str,
	payment_payload: dict[str, Any],
) -> tuple[bool, str | None]:
	"""
	Settle a previously verified x402 payment via the CDP facilitator.

	Call only after the gated tool has succeeded. Requirements are rebuilt
	server-side from tool_name (never from payer-supplied fields).
	"""
	if not is_tool_gated(tool_name):
		return True, None

	requirements = get_payment_requirements(tool_name)
	if not requirements.get('payTo'):
		return False, 'Payment receiving wallet not configured'

	ok, error, certainty = await _settle_with_facilitator(tool_name, payment_payload, requirements)
	if certainty == 'success':
		# Drop the live reservation; keep a bounded TTL replay entry so the nonce cannot be reused.
		await _complete_x402_payment(payment_payload)
	elif certainty == 'failed':
		# Facilitator rejected settlement before (or instead of) an on-chain transfer — retry is safe.
		await release_x402_payment(payment_payload)
	# Ambiguous (timeout / 5xx / transport): keep the reservation until status can be reconciled.
	# A retry must not be admitted to run the gated tool again while /settle may still have landed.
	return ok, error


async def _verify_with_facilitator(
	tool_name: str,
	payment_payload: dict[str, Any],
	payment_requirements: dict[str, Any],
) -> tuple[bool, str | None]:
	"""POST /verify against the configured CDP facilitator (no on-chain transfer)."""
	body = _facilitator_request_body(payment_payload, payment_requirements)
	client = _get_http_client()

	try:
		auth_headers = _facilitator_auth_headers('/verify')
	except ValueError as e:
		logger.error(f'CDP facilitator auth failed for /verify: {e}')
		return False, 'CDP facilitator credentials not configured'

	try:
		verify_response = await client.post(
			f'{CDP_FACILITATOR_URL}/verify',
			headers=auth_headers,
			json=body,
		)
	except httpx.TimeoutException:
		logger.error('CDP facilitator /verify timed out')
		return False, 'Payment verification timed out'
	except httpx.RequestError as e:
		logger.error(f'CDP facilitator /verify request failed: {e}')
		return False, 'Payment verification unavailable'

	if verify_response.status_code != 200:
		return False, _facilitator_error_message('verify', verify_response)

	verify_data = _decode_facilitator_json_object(verify_response)
	if verify_data is None:
		return False, 'Payment verification returned invalid JSON'

	if verify_data.get('isValid') is not True:
		reason = verify_data.get('invalidMessage') or verify_data.get('invalidReason') or 'Payment invalid'
		logger.debug(f'✗ Facilitator rejected payment for {tool_name}: {reason}')
		return False, str(reason)

	logger.debug(f'✓ Verified x402 payment for {tool_name} (not yet settled)')
	return True, None


def _settle_http_certainty(status_code: int) -> SettleCertainty:
	"""Classify a non-200 /settle HTTP status: 5xx/timeout-like codes may still have reached the facilitator."""
	if status_code >= 500 or status_code in {408, 429}:
		return 'ambiguous'
	return 'failed'


async def _settle_with_facilitator(
	tool_name: str,
	payment_payload: dict[str, Any],
	payment_requirements: dict[str, Any],
) -> tuple[bool, str | None, SettleCertainty]:
	"""POST /settle against the configured CDP facilitator (on-chain transfer).

	Returns (ok, error, certainty). certainty='ambiguous' means the request may have
	reached the facilitator; the caller must retain the local replay reservation.
	"""
	body = _facilitator_request_body(payment_payload, payment_requirements)
	client = _get_http_client()

	try:
		auth_headers = _facilitator_auth_headers('/settle')
	except ValueError as e:
		logger.error(f'CDP facilitator auth failed for /settle: {e}')
		# Auth never left this process — safe to treat as a definite failure.
		return False, 'CDP facilitator credentials not configured', 'failed'

	try:
		settle_response = await client.post(
			f'{CDP_FACILITATOR_URL}/settle',
			headers=auth_headers,
			json=body,
		)
	except httpx.TimeoutException:
		logger.error('CDP facilitator /settle timed out')
		return False, 'Payment settlement timed out', 'ambiguous'
	except httpx.RequestError as e:
		logger.error(f'CDP facilitator /settle request failed: {e}')
		return False, 'Payment settlement unavailable', 'ambiguous'

	if settle_response.status_code != 200:
		return False, _facilitator_error_message('settle', settle_response), _settle_http_certainty(settle_response.status_code)

	settle_data = _decode_facilitator_json_object(settle_response)
	if settle_data is None:
		# HTTP 200 with unreadable body: settlement may already have been accepted.
		return False, 'Payment settlement returned invalid JSON', 'ambiguous'

	# CDP / x402 facilitators return success=true on cleared settlement.
	if settle_data.get('success') is True or settle_data.get('isSuccessful') is True:
		logger.debug(f'✓ Settled x402 payment for {tool_name}')
		return True, None, 'success'

	reason = settle_data.get('errorReason') or settle_data.get('errorMessage') or settle_data.get('message')
	if reason:
		return False, f'Payment settlement failed: {reason}', 'failed'
	return False, 'Payment settlement failed', 'failed'


def _facilitator_error_message(action: str, response: httpx.Response) -> str:
	"""Extract a useful error string from a non-200 facilitator response."""
	logger.error(f'CDP facilitator /{action} error ({response.status_code}): {response.text}')
	data = _decode_facilitator_json_object(response)
	if data is None:
		return f'Payment {action} failed ({response.status_code})'

	detail = (
		data.get('invalidMessage')
		or data.get('errorMessage')
		or data.get('message')
		or data.get('errorReason')
		or data.get('detail')
	)
	if detail:
		return f'Payment {action} failed ({response.status_code}): {detail}'
	return f'Payment {action} failed ({response.status_code})'
