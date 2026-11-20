"""Browser Use web search: POST {gateway host}/api/v4/search with the Browser Use API key.

The REPL worker's search() asks the parent over its control channel (repl/session.py), and the parent makes the call
here: the API key never enters the worker. Request, response and errors as Browser Use Pi's worker search().
"""

from __future__ import annotations

import http.client
import json
import math
import re
import threading
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from browser_use.utils import urlopen_keyed

SEARCH_PATH = '/api/v4/search'
SEARCH_TIMEOUT_S = 25.0  # under the 120 s cell deadline: a hung endpoint fails the call, not the cell
HIT_SEPARATOR = re.compile(
	r'\n\n---\n\n(?=Title: )'
)  # the endpoint renders hits as one text; '---' also occurs inside highlights


class SearchError(RuntimeError):
	pass


def search_url(base_url: str) -> str:
	"""The search endpoint on the host of an API base URL ('https://api.browser-use.com/api/v4/llm/v1' ->
	'https://api.browser-use.com/api/v4/search')."""
	u = urlparse(base_url)
	return f'{u.scheme}://{u.netloc}{SEARCH_PATH}'


def parse_usd(value: Any) -> float | None:
	"""A charge as Browser Use reports it (a decimal string or a number) -> USD, or None when missing or invalid."""
	if not isinstance(value, (str, int, float)) or isinstance(value, bool):
		return None
	try:
		usd = float(value)
	except ValueError:
		return None
	return usd if math.isfinite(usd) and usd >= 0 else None


class WebSearch:
	"""One search per call. charges: the charge of each successful search whose response names one
	(browser_use.charge_usd); result.cost_usd adds them (agent/loop.py run). A response without one adds nothing."""

	def __init__(self, api_key: str, url: str):
		self.api_key, self.url = api_key, url
		self.charges: list[float] = []
		self._lock = threading.Lock()  # a cancelled call's thread can still finish while the next one runs

	def __call__(self, query: str, num_results: int | None = None, category: str | None = None) -> dict[str, Any]:
		if not isinstance(query, str) or not query.strip():
			raise SearchError('search(query) needs text.')
		body: dict[str, Any] = {'query': query}
		if num_results is not None:
			body['num_results'] = num_results
		if category is not None:
			body['category'] = category
		request = urllib.request.Request(
			self.url,
			data=json.dumps(body).encode(),
			method='POST',
			headers={'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'},
		)
		try:
			with urlopen_keyed(request, SEARCH_TIMEOUT_S) as r:
				text = r.read().decode('utf-8', 'replace')
		except urllib.error.HTTPError as e:
			detail = self._clean(e.read().decode('utf-8', 'replace')[:300])
			budget = ' (run out of budget)' if e.code == 402 else ''
			raise SearchError(f'Search failed: HTTP {e.code}{budget}: {detail}') from None
		except (TimeoutError, urllib.error.URLError) as e:
			if isinstance(e, TimeoutError) or isinstance(getattr(e, 'reason', None), TimeoutError):
				raise SearchError(f'Search failed: timed out after {SEARCH_TIMEOUT_S:g} s.') from None
			raise SearchError(f'Search failed: {self._clean(str(e))}') from None
		except OSError as e:  # reset mid-read
			raise SearchError(f'Search failed: {self._clean(str(e))}') from None
		try:
			parsed = json.loads(text)
		except ValueError:
			raise SearchError(f'Search returned non-JSON: {self._clean(text[:300])}') from None
		if not isinstance(parsed, dict):
			raise SearchError('Search returned no result object.')
		meta = parsed.get('browser_use')
		if (charge := parse_usd(meta.get('charge_usd')) if isinstance(meta, dict) else None) is not None:
			with self._lock:
				self.charges.append(charge)
		results = parsed.get('results')
		if isinstance(results, list):
			hits = results
		elif isinstance(results, str) and results.strip():
			hits = HIT_SEPARATOR.split(results)  # one entry per hit for the model
		else:
			hits = []
		return {**parsed, 'results': hits}

	def preflight(self) -> str | None:
		"""POST {} (free: no query, no search, no charge) before the browser starts. A missing endpoint (404), a
		rejected key (401/403) or no budget (402) is the error line. Anything else (422: there and the key works; 429,
		5xx, unreachable: maybe transient) is None: each search() call reports it, and the run goes on without search."""
		headers = {'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'}
		try:
			urlopen_keyed(urllib.request.Request(self.url, b'{}', headers, method='POST'), SEARCH_TIMEOUT_S).close()
		except urllib.error.HTTPError as e:
			if e.code in (401, 402, 403, 404):
				try:
					detail = self._clean(e.read().decode('utf-8', 'replace')[:300].strip())
				except (OSError, http.client.HTTPException):  # the body broke off: the status alone is the answer
					detail = e.reason
				return f'Agent(web_search=True): Browser Use web search at {self.url} answered HTTP {e.code}: {detail}'
		except (OSError, http.client.HTTPException):  # BadStatusLine, IncompleteRead are not OSError
			pass
		return None

	def _clean(self, text: str) -> str:
		return text.replace(self.api_key, '<api key>')
