"""The Browser Use API key: BROWSER_USE_API_KEY, else the key `browser-use login` stored (browser-harness's store)."""

import os

from browser_use.exceptions import MissingAPIKeyError


def browser_use_api_key(what: str = 'Browser Use Cloud') -> str:
	key = os.environ.get('BROWSER_USE_API_KEY')
	if key:
		return key
	from browser_harness.auth import stored_auth_record

	try:
		record = stored_auth_record() or {}
	except Exception:  # an unreadable auth file
		record = {}
	if not record.get('api_key'):
		raise MissingAPIKeyError(what)
	scopes = record.get('scopes') or []  # empty for a pasted key (--api-key-stdin): unknown, let the server decide
	if scopes and not any(s == '*:*:*' or s.startswith('v4:') for s in scopes):
		raise MissingAPIKeyError(what, v3_only=True)  # older logins minted v3 browser-only keys: 403 on API v4
	return str(record['api_key'])
