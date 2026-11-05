"""The Browser Use API key: BROWSER_USE_API_KEY, else the key `browser-use auth login` saved."""

import os

from browser_use.exceptions import MissingAPIKeyError


def browser_use_api_key(what: str = 'Browser Use Cloud') -> str:
	key = os.environ.get('BROWSER_USE_API_KEY')
	if key:
		return key
	from browser_harness.auth import get_browser_use_api_key

	try:
		return get_browser_use_api_key()
	except Exception:  # - CloudAuthRequired, or an unreadable auth file
		raise MissingAPIKeyError(what) from None
