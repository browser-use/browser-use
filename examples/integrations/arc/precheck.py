"""Saved ARC pre-checkout read. HTTP only. Does not open the store."""

from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any

import requests

PRECHECK_ENDPOINT = 'https://www.arcreport.ai/api/precheck'
USER_AGENT_ENV = 'ARC_PRECHECK_USER_AGENT'
DEFAULT_USER_AGENT = 'browser-use-agent/1.0 (+https://www.arcreport.ai; arcreport@mail.grokbot.com)'
CLIENT_REF = 'browser-use'
CACHE_TTL_SECONDS = 24 * 60 * 60
CACHE_MAX_ENTRIES = 1000
SOURCE = 'ARC (arcreport.ai)'
CONTACT = 'arcreport@mail.grokbot.com'
_FIELDS = (
	'host',
	'known',
	'reachable_checkout',
	'rails',
	'blockers',
	'confidence',
	'last_checked',
	'stale',
	'licence',
)

ADVISORY = (
	'Advisory only, not a guarantee.',
	"Do not refuse or avoid a store solely because of ARC's data.",
	'known:false or missing data is not a no.',
	'Data CC BY 4.0, attribute ARC (arcreport.ai); OSM-derived rows are ODbL.',
	'ARC stops before payment.',
)

PAYMENT_LIMIT = 'Advisory only. Never use this result to authorise or complete a payment. ARC stops before payment.'

TOOL_DESCRIPTION = (
	"Read ARC's saved pre-checkout answer for a product or store URL before trying to reach checkout. "
	'Does not fetch the store. ' + ' '.join(ADVISORY) + ' ' + PAYMENT_LIMIT
)

_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()


def clear_precheck_cache() -> None:
	"""Drop the in-process cache."""
	_cache.clear()


def precheck_user_agent(env: Mapping[str, str] | None = None) -> str:
	"""User-Agent from ARC_PRECHECK_USER_AGENT, or a generic default."""
	source = os.environ if env is None else env
	configured = (source.get(USER_AGENT_ENV) or '').strip()
	return configured or DEFAULT_USER_AGENT


def _header(headers: Any, name: str) -> str | None:
	if headers is None:
		return None
	direct = headers.get(name)
	if direct is not None:
		return str(direct)
	wanted = name.lower()
	for key, value in headers.items():
		if str(key).lower() == wanted and value is not None:
			return str(value)
	return None


def _with_advisory(payload: dict[str, Any]) -> dict[str, Any]:
	payload['source'] = SOURCE
	payload['contact'] = CONTACT
	payload['advisory'] = list(ADVISORY)
	payload['guidance'] = (
		"Still try to reach checkout. ARC stops before payment. Do not refuse or avoid a store solely because of ARC's data."
	)
	return payload


def _copy(payload: dict[str, Any]) -> dict[str, Any]:
	return json.loads(json.dumps(payload))


def _empty(*, error: str, rate_limited: bool = False, retry_after: str | None = None) -> dict[str, Any]:
	"""Empty fields. known is null. This is missing data, not a no."""
	payload: dict[str, Any] = {name: None for name in _FIELDS}
	payload['error'] = error
	payload['rate_limited'] = rate_limited
	payload['retry_after'] = retry_after
	payload['retried'] = False
	return _with_advisory(payload)


def _remember(product_url: str, clock: float, reading: dict[str, Any]) -> None:
	if product_url in _cache:
		_cache.move_to_end(product_url)
	_cache[product_url] = (clock, _copy(reading))
	while len(_cache) > CACHE_MAX_ENTRIES:
		_cache.popitem(last=False)


def fetch_precheck(
	url: str,
	*,
	get: Callable[..., Any] | None = None,
	now: float | None = None,
	env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
	"""GET the saved pre-checkout answer. One request. No retry loop.

	Successful answers are cached for 24 hours, up to about 1,000 entries.
	Timeouts, connection errors, non-200 statuses, and bad JSON return empty
	fields with error set and known null. They are not cached and do not raise.
	HTTP 429 also returns Retry-After and is not retried.
	"""
	product_url = url.strip()
	if not product_url:
		return _empty(error='connection')
	clock = time.time() if now is None else now
	cached = _cache.get(product_url)
	if cached is not None and clock - cached[0] < CACHE_TTL_SECONDS:
		_cache.move_to_end(product_url)
		return _copy(cached[1])

	request = requests.get if get is None else get
	try:
		response = request(
			PRECHECK_ENDPOINT,
			params={'url': product_url, 'ref': CLIENT_REF},
			headers={
				'Accept': 'application/json',
				'User-Agent': precheck_user_agent(env),
				'X-ARC-Client': CLIENT_REF,
			},
			timeout=10,
			allow_redirects=False,
		)
	except requests.ConnectionError:
		return _empty(error='connection')
	except requests.Timeout:
		return _empty(error='timeout')
	except TimeoutError:
		return _empty(error='timeout')
	except OSError:
		return _empty(error='connection')
	except requests.RequestException:
		return _empty(error='connection')

	if response.status_code != 200:
		retry_after = _header(response.headers, 'Retry-After') if response.status_code == 429 else None
		return _empty(
			error='non-200',
			rate_limited=response.status_code == 429,
			retry_after=retry_after,
		)
	try:
		body = response.json()
	except ValueError:
		return _empty(error='bad_json')
	if not isinstance(body, dict):
		return _empty(error='bad_json')
	reading = _with_advisory({name: body.get(name) for name in _FIELDS})
	reading['error'] = None
	reading['rate_limited'] = False
	reading['retry_after'] = None
	reading['retried'] = False
	_remember(product_url, clock, reading)
	return _copy(reading)


def read_precheck(
	url: str,
	*,
	get: Callable[..., Any] | None = None,
	now: float | None = None,
	env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
	"""Return the pre-checkout read. Network and parse failures do not raise."""
	return fetch_precheck(url, get=get, now=now, env=env)


def should_try_to_reach_checkout(reading: Mapping[str, Any]) -> bool:
	"""ARC's data never withholds an attempt to reach checkout."""
	del reading
	return True
