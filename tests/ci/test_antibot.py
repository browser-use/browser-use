"""Anti-bot block detection (repl/antibot.py): the rules on the cloud ground truth, the worker's probe on real Chrome
pages, result.blocks and the end-of-run warning."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from conftest import script

from browser_use import Agent, Browser
from browser_use.agent.views import AgentHistoryList
from browser_use.repl.antibot import ANY_HIT, PROBE_BUDGET_S, QUERIES, WALLS, WEAK, Block, BlockLog, Doc, blocks, classify

GROUNDTRUTH = json.loads((Path(__file__).parent / 'fixtures' / 'antibot' / 'groundtruth.json').read_text(encoding='utf-8'))
QUERY_NAMES = {q: name for name, q in QUERIES.items()}


def replay(visit: dict, latency: float = 0.0) -> dict:
	"""One ground-truth visit through BlockLog: its main documents as events, then one probe of the final page, from a
	daemon that answers each call after latency seconds (a call given less times out)."""
	log = BlockLog()
	events: list[dict] = [{'method': 'Page.frameNavigated', 'params': {'frame': {'id': 'F'}}}]
	for i, d in enumerate(visit['docs']):
		response = {'status': d['status'], 'url': d['url'], 'headers': d['headers'], 'mimeType': d['mime']}
		params = {'type': 'Document', 'frameId': 'F', 'loaderId': f'L{i}', 'timestamp': 1000 + d['t'], 'response': response}
		events.append({'method': 'Network.responseReceived', 'params': params})
	log.observe(events)
	loader = f'L{max(len(visit["docs"]) - 1, 0)}'

	def cdp(method, _response_timeout=None, **params):
		if _response_timeout is not None and latency > _response_timeout:
			raise TimeoutError(f'{method} timed out after {_response_timeout}s waiting for the daemon')
		if method == 'Page.getFrameTree':
			frame = {'id': 'F', 'loaderId': loader, 'url': visit['final_url'], 'mimeType': 'text/html'}
			return {'frameTree': {'frame': frame}}
		if method == 'Target.getTargetInfo':
			return {'targetInfo': {'title': visit['title']}}
		if method == 'DOM.performSearch' and params['query'] == ANY_HIT:
			return {'searchId': 's', 'resultCount': sum(n for name, n in visit['hits'].items() if name not in WEAK)}
		if method == 'DOM.performSearch':
			return {'searchId': 's', 'resultCount': visit['hits'].get(QUERY_NAMES[params['query']], 0)}
		return {}

	log.probe(cdp)
	found = log.take()['visits']
	return found[-1] if found else {'outcome': 'ok', 'vendor': ''}


def test_groundtruth_every_wall_found_no_clean_page_flagged_and_cleared_challenges_pass():
	"""DESIGN §3.4 on the 126 labeled cloud visits: each page left walled at 22 s is a wall, no page that ended usable
	is one, and each 4xx-then-200 visit is 'passed'. Without a main document (vueling's ERR_HTTP2_PROTOCOL_ERROR,
	spirit's SOCKS failure) there is nothing to classify: those stay in telemetry's nav_errors."""
	missed, false_walls, not_passed = [], [], []
	for v in GROUNDTRUTH['visits']:
		r = replay(v)
		wall = r['outcome'] in WALLS
		if v['label'] in ('blocked', 'challenge') and v['docs'] and not wall:
			missed.append(v['id'])
		if v['label'] == 'ok' and wall:
			false_walls.append((v['id'], r))
		statuses = [d['status'] for d in v['docs']]
		if v['label'] == 'ok' and len(statuses) > 1 and statuses[-1] == 200 and any(s >= 400 or s == 202 for s in statuses):
			if r['outcome'] != 'passed':
				not_passed.append((v['id'], r))
	bad = [v for v in GROUNDTRUTH['visits'] if v['label'] in ('blocked', 'challenge')]
	assert len(bad) == 12 and sum(not v['docs'] for v in bad) == 1  # vueling
	assert missed == [] and false_walls == [] and not_passed == []


@pytest.mark.parametrize(
	('visit_id', 'outcome', 'vendor'),
	[
		('noproxy__p1__hermes.com', 'stuck', 'datadome'),  # captcha iframe inside a 200 with a normal title
		('noproxy__p1__whoscored.com', 'blocked', 'cloudflare'),
		('noproxy__p1__hyatt.com', 'blocked', 'kasada'),  # 429 1-AA that never cleared
		('noproxy__p2__adidas.com', 'blocked', 'akamai'),
		('proxy__p2__lowes.com', 'blocked', 'akamai'),  # Akamai's reference-code page served with 200
		('proxy__p2__amazon.com', 'blocked', 'amazon'),
		('noproxy__p2__indeed.com', 'stuck', 'cloudflare'),
		('noproxy__p1__stockx.com', 'blocked', 'unknown'),  # a custom 403 with no vendor header
		('noproxy__p2__idealista.com', 'passed', 'datadome'),  # 403 x-dd-b, then 200
		('proxy__p1__booking.com', 'passed', 'unknown'),  # AWS WAF 202 without its header on the proxy
		('noproxy__p1__leboncoin.fr', 'ok', ''),  # x-datadome: protected is presence, not a block
	],
)
def test_groundtruth_vendor_and_outcome(visit_id, outcome, vendor):
	r = replay(next(v for v in GROUNDTRUTH['visits'] if v['id'] == visit_id))
	assert (r['outcome'], r.get('vendor', '')) == (outcome, vendor)


def test_a_daemon_slow_to_answer_still_gets_a_verdict():
	"""On a loaded machine the daemon took over 1 s per call: each probe timed out and hermes' DataDome captcha, seen only
	in the DOM of a 200, went unreported once the agent moved on. Calls now wait up to PROBE_CALL_S within the budget."""
	(hermes,) = (v for v in GROUNDTRUTH['visits'] if v['id'] == 'noproxy__p1__hermes.com')
	assert replay(hermes, latency=1.5)['vendor'] == 'datadome'
	assert replay(hermes, latency=PROBE_BUDGET_S + 1)['outcome'] == 'ok'  # never past the budget: no verdict, no wait


def test_an_akamai_netstorage_403_is_akamai():
	"""adidas from a datacenter IP: a 403 deny page served from Akamai NetStorage, with no other Akamai header."""
	verdict = classify(Doc(403, {'server': 'AkamaiNetStorage', 'content-type': 'text/html'}, 'https://www.adidas.com/us'))
	assert (verdict.outcome, verdict.vendor, verdict.signal) == ('blocked', 'akamai', 'akamai_403')


def test_an_api_error_is_not_a_wall():
	assert (
		classify(Doc(403, {'server': 'cloudflare', 'cf-ray': 'x'}, 'https://api.example.com/v1', 'application/json')).outcome
		== 'ok'
	)


def test_a_cloud_browser_reports_its_own_verdicts_and_skips_the_local_rules():
	log = BlockLog(remote=True)
	response = {'status': 403, 'url': 'https://shop.example/', 'headers': {'x-dd-b': '1'}, 'mimeType': 'text/html'}
	verdict = {'targetId': 'T', 'visitId': 'V1', 'outcome': 'blocked', 'challenge': 'captcha', 'vendor': 'datadome'}
	log.observe(
		[
			{'method': 'Page.frameNavigated', 'params': {'frame': {'id': 'T'}}},
			{'method': 'Network.responseReceived', 'params': {'type': 'Document', 'frameId': 'T', 'response': response}},
			{'method': 'BrowserUse.blockDetected', 'params': {**verdict, 'host': 'shop.example', 'status': 403}},
		]
	)
	log.probe(lambda method, **params: pytest.fail(f'a cloud browser was probed: {method}'))
	assert log.take()['visits'] == [
		{
			'id': 'V1',
			'host': 'shop.example',
			'url': '',
			'outcome': 'blocked',
			'challenge': 'captcha',
			'vendor': 'datadome',
			'signal': '',
			'confidence': 95,
			'statuses': [403],
		}
	]


def test_blocks_group_visits_by_vendor_host_and_outcome():
	visits = {
		'a': {'outcome': 'blocked', 'vendor': 'datadome', 'host': 'x.com', 'statuses': [403]},
		'b': {'outcome': 'blocked', 'vendor': 'datadome', 'host': 'x.com', 'statuses': [403]},
		'c': {'outcome': 'passed', 'vendor': 'cloudflare', 'host': 'y.com', 'statuses': [403, 200]},
		'd': {'outcome': 'rate_limited', 'vendor': '', 'host': 'z.com', 'statuses': [429]},
	}
	assert [str(b) for b in blocks(visits)] == ['DataDome on x.com (2x)', 'an anti-bot (HTTP 429) on z.com']


# --- real Chrome: the worker's probe, result.blocks and the warning ---

DD_PAGE = """<html><head><title>Example shop</title></head><body><p>Please enable JS and disable any ad blocker</p>
<iframe src="/geo.captcha-delivery.com/captcha/?initialCid=x&t=bv" width="10" height="10"></iframe></body></html>"""
CF_PAGE = """<html><head><title>Attention Required! | Cloudflare</title></head><body><h1>Sorry, you have been blocked</h1>
<p>You are unable to access this site.</p></body></html>"""
OK_PAGE = """<html><head><title>Products</title></head><body><h1>Products</h1><p>A page that loads.</p>
<iframe src="/www.google.com/recaptcha/api2/aframe" width="1" height="1"></iframe></body></html>"""
CHALLENGE_PAGE = """<html><head><title>Just a moment...</title></head><body><p>Checking your browser.</p>
<script>setTimeout(() => location.replace('/cleared'), 300)</script></body></html>"""
PAGES = {
	'/dd': (403, {'X-DataDome': 'protected', 'Server': 'DataDome'}, DD_PAGE),
	'/cf': (403, {'Server': 'cloudflare', 'CF-RAY': '8a1b2c3d4e5f-CMH'}, CF_PAGE),
	'/ok': (200, {'X-DataDome': 'protected'}, OK_PAGE),  # vendor present, no block
	'/challenge': (403, {'Server': 'cloudflare', 'cf-mitigated': 'challenge', 'CF-RAY': 'x'}, CHALLENGE_PAGE),
	'/cleared': (200, {'Server': 'cloudflare', 'CF-RAY': 'y'}, OK_PAGE),
	'/api': (403, {'Server': 'cloudflare', 'CF-RAY': 'z'}, '{"error": "forbidden"}'),
}


@pytest.fixture
def antibot_site():
	class Handler(BaseHTTPRequestHandler):
		def do_GET(self):
			status, headers, body = PAGES.get(self.path.split('?')[0], (404, {}, 'not found'))
			data = body.encode()
			self.send_response(status)
			for k, v in headers.items():
				self.send_header(k, v)
			self.send_header('Content-Type', 'application/json' if self.path == '/api' else 'text/html')
			self.send_header('Content-Length', str(len(data)))
			self.end_headers()
			self.wfile.write(data)

		def log_message(self, *a):
			pass

	server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield server.server_address[1]
	server.shutdown()


async def test_a_local_run_reports_each_wall_once_with_the_cloud_link(chrome, tmp_path, antibot_site, caplog, monkeypatch):
	"""Real Chrome, real worker: a DataDome IP ban and a Cloudflare block page are walls; a DataDome-protected page that
	loads, a challenge that clears itself and an API's 403 are not. Hosts differ (*.localhost): a same-site page soon
	after a wall continues its visit."""
	monkeypatch.delenv('BROWSER_USE_CLOUD_HINTS', raising=False)
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)  # caplog listens on the root logger
	port = antibot_site
	cells = [
		f"goto_url('http://dd.localhost:{port}/dd'); wait_for_load()",
		f"goto_url('http://cf.localhost:{port}/cf'); wait_for_load()",
		f"goto_url('http://ok.localhost:{port}/ok'); wait_for_load()",
		f"goto_url('http://chl.localhost:{port}/challenge'); wait_for_load(); time.sleep(1.5)",
		f"goto_url('http://api.localhost:{port}/api'); wait_for_load()",
	]
	model, _ = script(
		*[('python', {'code': f'import time\n{c}'}) for c in cells], ('finish', {'success': False, 'result': 'blocked'})
	)
	with caplog.at_level(logging.WARNING, logger='browser_use'):
		result = await Agent('Buy socks', model, browser=Browser(cdp_url=chrome['http']), workspace=tmp_path).run()
	assert result.status == 'completed', result.error
	assert [(b.vendor, b.host, b.outcome) for b in result.blocks] == [
		('datadome', 'dd.localhost', 'blocked'),
		('cloudflare', 'cf.localhost', 'blocked'),
	]
	warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and 'Blocked by' in r.getMessage()]
	assert warnings == [
		'Blocked by DataDome on dd.localhost, Cloudflare on cf.localhost. Cloud browsers pass most anti-bots, Browser() runs '
		'one: https://cloud.browser-use.com/?utm_source=oss&utm_medium=block_nudge&utm_content=datadome'
	]
	assert 'blocks=[DataDome on dd.localhost, Cloudflare on cf.localhost]' in repr(result)


def result_with(*walls: Block, success: bool | None = None) -> AgentHistoryList:
	from browser_use.agent.judge import Judgement

	usage = {'input': 0, 'output': 0, 'cache_read': 0, 'cache_write': 0, 'requests': 0}
	r = AgentHistoryList('completed', '', None, 1, 1.0, usage, 0.0, None, None, [])
	r.blocks = list(walls)
	if success is not None:
		r.judgement = Judgement(
			success=success, description='d', prompt_injection_detected=False, bot_block_or_captcha_detected=True
		)
	return r


def notices(agent: Agent, result: AgentHistoryList, caplog) -> list[str]:
	caplog.clear()
	with caplog.at_level(logging.WARNING, logger='browser_use'):
		agent._block_notice(result)
	return [r.getMessage() for r in caplog.records]


def test_the_warning_names_a_proxy_on_cloud_and_honors_cloud_hints_off(tmp_path, caplog, monkeypatch):
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)
	dd = Block('datadome', 'www.example.com', 'blocked', 3, statuses=[403])
	model, _ = script()
	cloud = Agent('t', model, browser=Browser(cloud_proxy_country_code='us'), workspace=tmp_path)
	assert notices(cloud, result_with(dd), caplog) == [
		'Blocked by DataDome on www.example.com (3x) on a Browser Use cloud browser (us proxy). Another exit country may '
		"pass: Browser(cloud_proxy_country_code='de')"
	]
	local = Agent('t', model, browser=Browser('chromium'), workspace=tmp_path)
	assert notices(local, result_with(dd, success=True), caplog) == []  # got through: the judge says so
	monkeypatch.setenv('BROWSER_USE_CLOUD_HINTS', 'false')
	assert notices(local, result_with(dd, success=False), caplog) == ['Blocked by DataDome on www.example.com (3x)']
