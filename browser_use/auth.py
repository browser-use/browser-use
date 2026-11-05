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
	# Scopes are the server's to judge: a key it rejects (an older login's v3 browser-only key) gets a 403 that the
	# cloud and gateway errors turn into "run `browser-use login` again".
	return str(record['api_key'])
