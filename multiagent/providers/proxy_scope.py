"""Context manager that sets http_proxy/https_proxy only for the duration of a block."""

from __future__ import annotations

import os
from contextlib import contextmanager


@contextmanager
def proxy_scope(proxy_url: str | None):
	"""Set HTTP(S) proxy env vars for the duration of the block, then restore originals.

	If proxy_url is None, this is a no-op.
	"""
	if proxy_url is None:
		yield
		return

	saved = {}
	keys = ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY')
	for k in keys:
		saved[k] = os.environ.get(k)
		os.environ[k] = proxy_url

	try:
		yield
	finally:
		for k in keys:
			if saved[k] is None:
				os.environ.pop(k, None)
			else:
				os.environ[k] = saved[k]
