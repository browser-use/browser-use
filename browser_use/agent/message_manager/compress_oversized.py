"""Optional preview for text that would otherwise be prefix-cut.

Unset SUPERCOMPRESS_API_KEY and this module never runs. A failed call, a
timeout, or a result that is not shorter keeps the existing prefix cut.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

SUPERCOMPRESS_URL = 'https://api.supercompress.dev/v1/compress'
MAX_CONTEXT_CHARS = 120_000
MAX_QUERY_CHARS = 4_000
REQUEST_TIMEOUT_S = 5.0
CONTENT_CAP_NOTICE = '\n... [Content truncated at 60k characters]'


def prefix_cut(text: str, cap: int) -> str:
	"""The cut MessageManager already applies once text exceeds ``cap``."""
	if len(text) <= cap:
		return text
	return text[:cap] + CONTENT_CAP_NOTICE


def choose_compress_target(lengths: dict[str, int], cap: int) -> str | None:
	"""Name of the single longest string that exceeds ``cap``, if any."""
	oversized = {name: size for name, size in lengths.items() if size > cap}
	if not oversized:
		return None
	return max(oversized, key=lambda name: oversized[name])


def fit_to_cap(
	text: str,
	cap: int,
	*,
	query: str | None,
	enabled: bool,
	api_key: str | None = None,
	opener=None,
) -> str:
	"""Return ``text`` if it fits. Otherwise try one compress call, then the prefix cut.

	``enabled`` is set on only one string per history update, so two oversized
	fields still produce at most one request.
	"""
	if len(text) <= cap:
		return text
	compressed = None
	if enabled:
		compressed = compress_context(
			text,
			query or '',
			api_key if api_key is not None else os.environ.get('SUPERCOMPRESS_API_KEY', ''),
			opener=opener,
		)
	body = compressed if compressed else text
	if compressed and len(compressed) <= cap:
		logger.debug('supercompress chars %s -> %s', len(text), len(compressed))
		return compressed
	if compressed:
		logger.debug('supercompress chars %s -> %s, still over cap', len(text), len(compressed))
	return prefix_cut(body, cap)


def compress_context(
	context: str,
	query: str,
	api_key: str,
	*,
	opener=None,
	timeout: float = REQUEST_TIMEOUT_S,
) -> str | None:
	"""POST {context, query}. Return compressed_text only when it is shorter."""
	key = api_key.strip()
	query = query.strip()[:MAX_QUERY_CHARS]
	if not key or not query or not context or len(context) > MAX_CONTEXT_CHARS:
		return None
	payload = json.dumps({'context': context, 'query': query}).encode()
	request = urllib.request.Request(
		SUPERCOMPRESS_URL,
		data=payload,
		headers={'Content-Type': 'application/json', 'X-API-Key': key},
		method='POST',
	)
	open_url = opener or urllib.request.urlopen
	try:
		with open_url(request, timeout=timeout) as response:
			raw = response.read()
	except urllib.error.HTTPError as exc:
		logger.warning('supercompress skipped status=%s', exc.code)
		return None
	except Exception as exc:
		logger.warning('supercompress skipped: %s', type(exc).__name__)
		return None
	try:
		body = json.loads(raw.decode())
	except (UnicodeError, json.JSONDecodeError):
		return None
	text = body.get('compressed_text') if isinstance(body, dict) else None
	if not isinstance(text, str) or not text or len(text) >= len(context):
		return None
	return text
