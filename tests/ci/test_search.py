"""Agent(web_search=...): search() in the REPL, answered by the parent against a fake /api/v4/search. No browser."""

import json
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import script
from pydantic_ai.models.function import FunctionModel

from browser_use import Agent, Browser, ChatBrowserUse
from browser_use.agent.loop import Session, build_agent, run
from browser_use.agent.prompt import LOCAL_PROMPT, SEARCH_PROMPT, SYSTEM_PROMPT
from browser_use.exceptions import MissingAPIKeyError
from browser_use.repl import Repl
from browser_use.search import SearchError, WebSearch, search_url

KEY = 'bu_test_search_key'
HITS = {
	'query': 'q',
	'count': 2,
	'results': 'Title: A\nURL: https://a.example\nHighlights:\nintro\n\n---\n\nmore of A\n\n---\n\nTitle: B',  # a '---' rule inside A's highlights
	'browser_use': {'charge_usd': '0.007'},
}


@pytest.fixture
def endpoint():
	"""A fake search endpoint: set .reply = (status, body bytes or JSON value, delay s); .seen holds requests."""

	class State:
		reply: tuple = (200, HITS, 0)
		seen: list = []

	state = State()

	class Handler(BaseHTTPRequestHandler):
		def do_POST(self):
			body = self.rfile.read(int(self.headers['Content-Length']))
			state.seen.append({'path': self.path, 'headers': dict(self.headers), 'body': json.loads(body)})
			status, out, delay = state.reply
			time.sleep(delay)
			data = out if isinstance(out, bytes) else json.dumps(out).encode()
			try:
				self.send_response(status)
				self.send_header('Content-Type', 'application/json')
				self.send_header('Content-Length', str(len(data)))
				self.end_headers()
				self.wfile.write(data)
			except OSError:  # the client gave up (timeout test)
				pass

		def log_message(self, *args):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	server.daemon_threads = True
	threading.Thread(target=server.serve_forever, daemon=True).start()
	state.base = f'http://127.0.0.1:{server.server_address[1]}'  # type: ignore[attr-defined]
	state.url = search_url(f'{state.base}/api/v4/llm/v1')  # type: ignore[attr-defined]
	yield state
	server.shutdown()
	server.server_close()


def test_search_url_is_the_gateway_host():
	assert search_url('https://api.browser-use.com/api/v4/llm/v1') == 'https://api.browser-use.com/api/v4/search'
	assert search_url('http://127.0.0.1:8080/api/v4/llm/v1/') == 'http://127.0.0.1:8080/api/v4/search'


def test_request_shape_and_result_parsing(endpoint):
	search = WebSearch(KEY, endpoint.url)
	r = search('pages about X', num_results=3, category='news')
	sent = endpoint.seen[-1]
	assert sent['path'] == '/api/v4/search'
	assert sent['headers']['Authorization'] == f'Bearer {KEY}'  # as the gateway LLM sends it
	assert sent['headers']['Content-Type'] == 'application/json'
	assert sent['body'] == {'query': 'pages about X', 'num_results': 3, 'category': 'news'}
	assert r['results'] == [
		'Title: A\nURL: https://a.example\nHighlights:\nintro\n\n---\n\nmore of A',
		'Title: B',
	]  # one entry per hit
	assert (r['query'], r['count']) == ('q', 2)
	search('only a query')
	assert endpoint.seen[-1]['body'] == {'query': 'only a query'}  # unset options are not sent
	endpoint.reply = (200, {'query': 'q', 'count': 1, 'results': [{'title': 'A', 'url': 'https://a.example'}]}, 0)
	assert search('q')['results'] == [{'title': 'A', 'url': 'https://a.example'}]  # a list passes through
	endpoint.reply = (200, {'query': 'q', 'count': 0, 'results': ''}, 0)
	assert search('q')['results'] == []
	assert search.charges == [0.007, 0.007]  # a response naming no charge adds none
	with pytest.raises(SearchError, match='needs text'):
		search('  ')


@pytest.mark.parametrize(
	('reply', 'message'),
	[
		((402, {'error': 'no credits'}, 0), r'^Search failed: HTTP 402 \(run out of budget\): {"error": "no credits"}$'),
		((500, b'upstream down', 0), r'^Search failed: HTTP 500: upstream down$'),
		((200, b'<html>not json</html>', 0), r'^Search returned non-JSON: <html>not json</html>$'),
		((200, ['a list'], 0), r'^Search returned no result object\.$'),
		((200, HITS, 2), r'^Search failed: timed out after 0\.5 s\.$'),
	],
)
def test_errors(endpoint, monkeypatch, reply, message):
	monkeypatch.setattr('browser_use.search.SEARCH_TIMEOUT_S', 0.5)
	endpoint.reply = reply
	search = WebSearch(KEY, endpoint.url)
	with pytest.raises(SearchError, match=message):
		search('q')
	assert search.charges == []  # a failed search is not counted as charged


def test_error_text_never_carries_the_key(endpoint):
	endpoint.reply = (401, f'bad key {KEY}'.encode(), 0)
	with pytest.raises(SearchError) as e:
		WebSearch(KEY, endpoint.url)('q')
	assert KEY not in str(e.value) and '<api key>' in str(e.value)


@pytest.mark.parametrize(
	('raw', 'expected'),
	[
		(b'garbage, not HTTP\r\n\r\n', None),  # http.client.BadStatusLine: not an OSError, escaped Agent.run()
		(  # a 401 whose body breaks off: IncompleteRead from e.read() escaped the except block
			b'HTTP/1.1 401 Unauthorized\r\nContent-Length: 100\r\n\r\nshort',
			'answered HTTP 401: Unauthorized',
		),
	],
)
def test_preflight_never_raises_on_a_broken_response(raw, expected):
	import socket

	server = socket.create_server(('127.0.0.1', 0))

	def answer():
		conn, _ = server.accept()
		with conn:
			conn.settimeout(10)
			conn.recv(65536)
			conn.sendall(raw)
			# close only after the client did: closing with its POST body unread sent Windows' RST, which the client
			# read as a network error (None) instead of the answer
			try:
				conn.shutdown(socket.SHUT_WR)
				while conn.recv(65536):
					pass
			except OSError:  # the client reset or never closed: the answer was sent
				pass

	threading.Thread(target=answer, daemon=True).start()
	try:
		line = WebSearch(KEY, f'http://127.0.0.1:{server.getsockname()[1]}/api/v4/search').preflight()
	finally:
		server.close()
	assert line is None if expected is None else (line and line.endswith(expected)), line


async def test_repl_search_is_answered_by_the_parent(endpoint, tmp_path, monkeypatch):
	monkeypatch.setattr('browser_use.search.SEARCH_TIMEOUT_S', 0.5)
	repl = Repl(tmp_path, search=WebSearch(KEY, endpoint.url))
	try:
		r = await repl.call('exec', "r = search('x', num_results=2)\nprint(r['count'], r['results'])", 30)
		assert r['error'] is None and "'Title: B']" in r['output'] and r['output'].startswith('2 ')
		assert endpoint.seen[-1]['body'] == {'query': 'x', 'num_results': 2}
		assert r['stats']['helpers'] == {'search': 1}  # telemetry counts the helper
		# the key stays in the parent: not in the worker's environment, globals or search()'s closure
		dig = 'import inspect, os\nf = inspect.unwrap(search)\nprint(os.environ, [c.cell_contents for c in f.__closure__ or ()])'
		assert KEY not in (await repl.call('exec', dig, 30))['output']
		endpoint.reply = (402, {'error': 'no credits'}, 0)
		r = await repl.call('exec', "search('x')", 30)
		assert 'RuntimeError: Search failed: HTTP 402 (run out of budget)' in r['error']
		endpoint.reply = (200, HITS, 2)
		r = await repl.call('exec', "search('x')", 30)
		assert 'Search failed: timed out after 0.5 s.' in r['error']
		r = await repl.call('exec', "search('x', num_results='5')", 30)
		assert 'TypeError: num_results must be an int' in r['error']
		r = await repl.call(
			'exec', "import threading\nt = threading.Thread(target=lambda: print(search('x')))\nt.start(); t.join()", 30
		)
		assert 'search() runs on the main thread only' in r['output']
		endpoint.reply = (200, HITS, 0)
		r = await repl.call('exec', "search('after errors')['count']", 30)  # the channel is still in step
		assert (r['output'].strip(), r['error']) == ('2', None)
	finally:
		await repl.close()


async def test_repl_without_search_has_no_search(tmp_path):
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', 'search', 30)
		assert "NameError: name 'search' is not defined" in r['error']
	finally:
		await repl.close()


def charged_script(*turns):
	"""script(), each response charged 0.001 as the gateway reports it."""
	model, _ = script(*turns)
	inner = model.function

	def fn(messages, info):
		return replace(inner(messages, info), provider_details={'browser_use': {'charge_usd': '0.001'}})  # type: ignore[arg-type]

	return FunctionModel(fn)


async def test_search_charges_are_added_to_cost(endpoint, tmp_path):
	"""result.cost_usd = model cost + what each search charged; a search without a charge adds nothing."""
	turns = (('python', {'code': "search('a'); search('b')"}), ('finish', {'result': 'done'}))
	repl = Repl(tmp_path, search=WebSearch(KEY, endpoint.url))
	try:
		r = await run(build_agent(charged_script(*turns)), 'task', Session(repl=repl), 'browser-use:bu-fast')
		assert r.cost_usd == pytest.approx(2 * 0.001 + 2 * 0.007)
		r = await run(build_agent(charged_script(turns[1])), 'task', Session(repl=repl), 'browser-use:bu-fast')
		assert r.cost_usd == pytest.approx(0.001)  # earlier runs' searches are not counted again
		endpoint.reply = (200, {'query': 'q', 'count': 0, 'results': []}, 0)  # no browser_use.charge_usd
		r = await run(build_agent(charged_script(*turns)), 'task', Session(repl=repl), 'browser-use:bu-fast')
		assert r.cost_usd == pytest.approx(2 * 0.001)  # the model cost stays; never None for an uncharged search
		endpoint.reply = (200, HITS, 0)  # charged again, but the model cost is unknown (an unpriced model)
		r = await run(build_agent(script(*turns)[0]), 'task', Session(repl=repl), 'browser-use:bu-fast')
		assert r.cost_usd is None
	finally:
		await repl.close()


def built(monkeypatch, tmp_path, key: str | None, browser=None, llm='test', **kw) -> Agent:
	if key:
		monkeypatch.setenv('BROWSER_USE_API_KEY', key)
	else:
		monkeypatch.delenv('BROWSER_USE_API_KEY', raising=False)
	agent = Agent('t', llm, browser=browser or Browser('chromium'), workspace=tmp_path, **kw)
	agent._build()
	return agent


def instructions(agent: Agent) -> str:
	return '\n'.join(i.instruction for i in agent._agent._instructions if isinstance(i.instruction, str))


@pytest.mark.parametrize(
	('kw', 'key', 'browser_kw', 'on'),
	[
		({}, KEY, {}, False),  # off by default, even with a key
		({'web_search': False}, KEY, {}, False),
		({'web_search': True}, KEY, {}, True),
		({'web_search': True}, KEY, {'prohibited_domains': ['evil.com']}, True),
	],
)
def test_enable_rule(monkeypatch, tmp_path, kw, key, browser_kw, on):
	agent = built(monkeypatch, tmp_path, key, Browser('chromium', **browser_kw), **kw)
	assert (agent._search is not None) == on
	assert (SEARCH_PROMPT in instructions(agent)) == on
	if on:
		assert agent._search and (agent._search.api_key, agent._search.url) == (KEY, 'https://api.browser-use.com/api/v4/search')


def test_web_search_with_allowed_domains_raises(monkeypatch, tmp_path):
	with pytest.raises(ValueError, match='cannot be combined with allowed_domains'):
		built(monkeypatch, tmp_path, KEY, Browser('chromium', allowed_domains=['example.com']), web_search=True)


def test_web_search_true_without_a_key_raises(monkeypatch, tmp_path):
	with pytest.raises(MissingAPIKeyError, match=r'^Agent\(web_search=True\) needs a Browser Use API key'):
		built(monkeypatch, tmp_path, None, web_search=True)


def test_bad_web_search_value_raises(tmp_path):
	with pytest.raises(TypeError, match='web_search must be True or False'):
		Agent('t', 'test', browser=Browser('chromium'), workspace=tmp_path, web_search='yes')  # type: ignore[arg-type]


def test_gateway_model_lends_its_key_and_host(monkeypatch, tmp_path):
	llm = ChatBrowserUse(api_key='bu_gateway_key', base_url='http://127.0.0.1:9/api/v4/llm/v1')
	agent = built(monkeypatch, tmp_path, None, llm=llm, web_search=True)
	assert agent._search and (agent._search.api_key, agent._search.url) == ('bu_gateway_key', 'http://127.0.0.1:9/api/v4/search')


def test_prompt_is_unchanged_when_search_is_off(monkeypatch, tmp_path):
	"""Off, the system prompt is the evaluated one byte for byte (plus the launched browser's downloads line); on, it
	gains exactly one SEARCH_PROMPT line."""
	off = instructions(built(monkeypatch, tmp_path, KEY, web_search=False))
	assert off == f'{SYSTEM_PROMPT}\n{LOCAL_PROMPT}' == instructions(built(monkeypatch, tmp_path, KEY))
	assert instructions(built(monkeypatch, tmp_path, KEY, web_search=True)) == f'{off}\n{SEARCH_PROMPT}'


async def test_missing_search_endpoint_fails_before_the_browser_starts(endpoint, monkeypatch, tmp_path):
	"""C37: with a provider model, a 404 search endpoint only showed up as 'HTTP 404' inside cells, and the agent burned
	steps on Google's captcha instead. The free POST {} preflight fails the run before any browser starts."""
	started = []

	async def start(self):
		started.append(self)
		raise RuntimeError('browser started')

	monkeypatch.setattr(Browser, 'start', start)
	agent = built(monkeypatch, tmp_path, KEY, web_search=True)
	assert agent._search
	agent._search.url = endpoint.url
	endpoint.reply = (404, b'404 page not found\n', 0)  # Go's plain-text 404
	result = await agent.run()
	assert (result.status, result.steps, started) == ('error', 0, [])
	assert (
		result.error == f'Agent(web_search=True): Browser Use web search at {endpoint.url} answered HTTP 404: 404 page not found'
	)
	assert endpoint.seen[-1]['body'] == {}  # no query: nothing searched, nothing charged
	endpoint.reply = (422, {'detail': 'query: Field required'}, 0)  # there, and the key works
	assert (await agent.run()).error == 'browser started'  # past the preflight: a failed start is a result too
	assert len(started) == 1
	# review: a transient outage (429/5xx) failed every web_search run; now the run starts and search() reports it
	for status in (429, 503):
		endpoint.reply = (status, b'busy', 0)
		agent._preflighted = False
		assert (await agent.run()).error == 'browser started'
	assert len(started) == 3
