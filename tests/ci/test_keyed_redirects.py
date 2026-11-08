"""GHSA-565j: a request that carries a Browser Use or provider API key never follows a redirect. urllib copies every
header to the new URL, so an endpoint that answered 302 to another origin received the key. No browser."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

KEY = 'bu_' + 'r' * 40


def _server(handle):
	class Handler(BaseHTTPRequestHandler):
		def do_GET(self):
			handle(self)

		do_POST = do_GET

		def log_message(self, *args):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	server.daemon_threads = True
	threading.Thread(target=server.serve_forever, daemon=True).start()
	return server, f'http://127.0.0.1:{server.server_address[1]}'


@pytest.fixture
def origins():
	"""first answers every request with 302 to the same path on second; second records what reaches it."""
	seen: list[dict] = []

	def record(h):
		seen.append({'path': h.path, 'headers': dict(h.headers)})
		h.send_response(200)
		h.send_header('Content-Length', '2')
		h.end_headers()
		h.wfile.write(b'{}')

	second, second_url = _server(record)

	def redirect(h):
		if n := int(h.headers.get('Content-Length') or 0):
			h.rfile.read(n)
		h.send_response(302)
		h.send_header('Location', f'{second_url}{h.path}')
		h.send_header('Content-Length', '0')
		h.end_headers()

	first, first_url = _server(redirect)
	yield first_url, seen
	for s in (first, second):
		s.shutdown()
		s.server_close()


def test_no_keyed_request_follows_a_redirect_to_another_origin(origins, monkeypatch):
	from browser_use import ChatBrowserUse, cli
	from browser_use.browser import browser as browser_mod
	from browser_use.search import SearchError, WebSearch, search_url

	first, seen = origins
	search = WebSearch(KEY, search_url(f'{first}/api/v4/llm/v1'))
	with pytest.raises(SearchError, match='HTTP 302'):
		search('q')
	assert search.preflight() is None  # a 3xx is not a verdict on the key: each search() reports it
	assert 'HTTP 302' in (ChatBrowserUse('bu-fast', api_key=KEY, base_url=f'{first}/api/v4/llm/v1').preflight() or '')

	monkeypatch.setenv('BROWSER_USE_API_KEY', KEY)
	monkeypatch.setattr(browser_mod, 'CLOUD_API', f'{first}/api/v4')
	with pytest.raises(RuntimeError, match='HTTP 302'):
		browser_mod._cloud('/browsers', 'POST', {})

	from browser_harness import auth

	monkeypatch.setenv('BROWSER_USE_CLOUD_API_URL', first)
	monkeypatch.setattr(auth, '_read_manual_api_key', lambda: KEY)
	assert cli._read_api_key_stdin() == KEY  # not a 401: stored, and the first cloud call reports it

	assert seen == []  # the second origin never got a request, so never the key
