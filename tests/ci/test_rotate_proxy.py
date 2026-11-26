"""rotate_proxy(): a new exit IP for the same Browser Use cloud browser. The cloud API is faked; no browser."""

import pytest

from browser_use import Browser
from browser_use.browser import browser as browser_mod
from browser_use.browser.browser import cloud_browser_id
from browser_use.repl import worker
from browser_use.repl.session import Repl

ID = '27ea6d2b-e818-4bb6-ba44-bd743ee4bc7b'


def test_cloud_browser_id_from_cdp_url():
	assert cloud_browser_id(f'https://{ID}.cdp.browser-use.com') == ID
	assert cloud_browser_id(f'wss://{ID.upper()}.cdp.browser-use.com/devtools/browser/{ID}') == ID
	for url in (None, '', 'http://127.0.0.1:9222', f'https://{ID}.cdp.browser-use.com.evil.test', f'https://x.{ID}.example.com'):
		assert cloud_browser_id(url) is None, url


def test_only_a_cloud_browser_offers_it_with_or_without_a_key(monkeypatch):
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	assert Browser(cdp_url=f'https://{ID}.cdp.browser-use.com').can_rotate_proxy()
	assert Browser().can_rotate_proxy()  # cloud, before it starts: the Agent builds its prompt before the browser has an id
	assert not Browser(cdp_url='http://127.0.0.1:9222').can_rotate_proxy()
	assert not Browser('chromium').can_rotate_proxy()
	monkeypatch.delenv('BROWSER_USE_API_KEY')
	monkeypatch.setattr(browser_mod, 'browser_use_api_key', lambda **k: (_ for _ in ()).throw(RuntimeError('no key')))
	b = Browser(cdp_url=f'https://{ID}.cdp.browser-use.com')
	assert b.can_rotate_proxy() and not b.has_rotate_key()  # BrowserUse.setProxy over CDP needs no key
	assert not Browser(cdp_url='http://127.0.0.1:9222').can_rotate_proxy()


@pytest.fixture
def proxy_api(monkeypatch):
	"""A fake /browsers/{id}/proxy: GET answers `ips[0]`, PATCH moves to the next IP (or `refuse` raises)."""
	state = {'ips': ['1.1.1.1', '2.2.2.2'], 'calls': [], 'refuse': None, 'lag': 0}

	def fake_cloud(path, method='GET', body=None):
		state['calls'].append((method, path, body))
		assert path == f'/browsers/{ID}/proxy'
		if method == 'PATCH':
			if state['refuse']:
				raise RuntimeError(state['refuse'])
			if state['lag'] == 0:
				state['ips'].pop(0)
			country = (body or {}).get('country', 'us')
			state['country'] = country
			return {'mode': 'managed', 'country': country, 'exitIp': state['ips'][0]}
		if state['lag'] and any(c[0] == 'PATCH' for c in state['calls']):
			state['lag'] -= 1
			if state['lag'] == 0:
				state['ips'].pop(0)
		return {'mode': 'managed', 'country': state.get('country', 'us'), 'exitIp': state['ips'][0]}

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	monkeypatch.setattr(browser_mod, '_cloud', fake_cloud)
	monkeypatch.setattr(browser_mod, 'PROXY_WAIT_S', 2.0)
	return state


async def test_rotate_proxy_returns_the_new_ip(proxy_api):
	b = Browser(cdp_url=f'https://{ID}.cdp.browser-use.com')
	assert await b.rotate_proxy('DE') == {'mode': 'managed', 'country': 'de', 'exitIp': '2.2.2.2'}
	assert proxy_api['calls'][1] == ('PATCH', f'/browsers/{ID}/proxy', {'rotate': True, 'country': 'de'})
	with pytest.raises(ValueError, match='2-letter code'):
		await b.rotate_proxy('germany')


async def test_rotate_proxy_waits_until_the_new_ip_is_live(proxy_api):
	proxy_api['lag'] = 2  # PATCH still reports the old IP; the second GET after it has the new one
	b = Browser(cdp_url=f'https://{ID}.cdp.browser-use.com')
	assert (await b.rotate_proxy())['exitIp'] == '2.2.2.2'
	assert [c[0] for c in proxy_api['calls']] == ['GET', 'PATCH', 'GET', 'GET']


async def test_rotate_proxy_explains_a_409(proxy_api):
	proxy_api['refuse'] = 'Browser Use Cloud PATCH /proxy failed: HTTP 409 Browser proxy unavailable'
	with pytest.raises(RuntimeError, match='agent session runs rotates its own proxy'):
		await Browser(cdp_url=f'https://{ID}.cdp.browser-use.com').rotate_proxy()


async def test_repl_rotate_proxy_is_answered_by_the_parent(tmp_path):
	asked = []

	async def rotate(country):
		asked.append(country)
		if country == 'zz':
			raise RuntimeError('HTTP 422 Invalid country')
		return {'mode': 'managed', 'country': country or 'us', 'exitIp': '9.9.9.9'}

	repl = Repl(tmp_path, rotate_proxy=rotate)
	try:
		r = await repl.call('exec', "print(rotate_proxy('de'))", 30)
		assert r['error'] is None and "'exitIp': '9.9.9.9'" in r['output'] and asked == ['de']
		assert r['stats']['helpers'] == {'rotate_proxy': 1}
		r = await repl.call('exec', "rotate_proxy('zz')", 30)
		assert 'rotate_proxy() failed: HTTP 422 Invalid country' in r['error']
		r = await repl.call('exec', "rotate_proxy()['country']", 30)  # the channel is still in step
		assert (r['output'].strip(), r['error']) == ('us', None)
	finally:
		await repl.close()


async def test_repl_without_a_cloud_browser_has_no_rotate_proxy(tmp_path):
	repl = Repl(tmp_path)
	try:
		r = await repl.call('exec', 'rotate_proxy', 30)
		assert "NameError: name 'rotate_proxy' is not defined" in r['error']
	finally:
		await repl.close()


async def test_cdp_first_falls_back_to_the_api_on_a_browser_without_the_method(daemon, tmp_path):
	"""Chrome has no BrowserUse.setProxy (our cloud browsers do): with a key the parent's API call answers instead."""
	asked = []

	async def rotate(country):
		asked.append(country)
		return {'mode': 'managed', 'country': country or 'us', 'exitIp': '9.9.9.9'}

	repl = Repl(tmp_path, daemon, rotate_proxy=rotate, rotate_proxy_cdp=True)
	try:
		r = await repl.call('exec', "print(rotate_proxy('de')['exitIp'])", 60)
		assert (r['error'], r['output'].strip(), asked) == (None, '9.9.9.9', ['de'])
	finally:
		await repl.close()


async def test_cdp_only_says_what_is_missing_on_a_browser_without_the_method(daemon, tmp_path):
	repl = Repl(tmp_path, daemon, rotate_proxy_cdp=True)
	try:
		r = await repl.call('exec', 'rotate_proxy()', 60)
		assert 'does not support it yet; set BROWSER_USE_API_KEY' in r['error']
	finally:
		await repl.close()


def _fake_cdp(answers):
	"""A CDP send for BrowserUse.setProxy: pops one answer per call (an Exception is raised), records the params."""
	sent = []

	def cdp(method, **params):
		assert method == 'BrowserUse.setProxy'
		sent.append(params)
		a = answers.pop(0)
		if isinstance(a, Exception):
			raise a
		return a

	return cdp, sent


def test_cdp_rotate_asks_for_a_new_ip_and_keeps_the_country_unless_given():
	cdp, sent = _fake_cdp(
		[{'mode': 'managed', 'country': 'us', 'exitIp': '2.2.2.2'}, {'mode': 'managed', 'country': 'de', 'exitIp': '3.3.3.3'}]
	)
	assert worker._cdp_rotate(cdp) == {'mode': 'managed', 'country': 'us', 'exitIp': '2.2.2.2'}
	assert worker._cdp_rotate(cdp, ' DE ')['exitIp'] == '3.3.3.3'
	assert sent == [{'rotate': True}, {'rotate': True, 'country': 'de'}]  # a country alone keeps the IP when already there


def test_cdp_rotate_turns_the_proxy_on_for_a_direct_browser():
	direct = RuntimeError(
		'BrowserUse.setProxy: invalid proxy change: a direct browser takes no country, provider, or rotate; send mode managed to turn the proxy on'
	)
	cdp, sent = _fake_cdp([direct, {'mode': 'managed', 'country': 'us', 'exitIp': '4.4.4.4'}])
	assert worker._cdp_rotate(cdp)['exitIp'] == '4.4.4.4'
	assert sent == [{'rotate': True}, {'mode': 'managed'}]


def test_cdp_rotate_passes_other_refusals_through():
	cdp, _ = _fake_cdp([RuntimeError('BrowserUse.setProxy: invalid proxy change: unknown country "zz"')])
	with pytest.raises(RuntimeError, match='unknown country'):
		worker._cdp_rotate(cdp, 'zz')


def test_rotate_hint_only_after_a_block_page_and_once_per_site():
	host = {'url': 'https://www.cwjobs.co.uk/jobs'}
	ns = {'rotate_proxy': object(), 'page_info': lambda: host}
	hinted: set = set()
	assert worker._rotate_hint(ns, "{'title': 'Jobs'} 25 results", hinted) == ''  # an ordinary page: nothing new
	assert worker._rotate_hint(ns, "{'title': 'Access Denied'}\nReference #18.4c85d817", hinted) == worker.ROTATE_HINT
	assert worker._rotate_hint(ns, 'Access Denied', hinted) == ''  # once per site
	host['url'] = 'https://www.zepto.com/cn'
	assert worker._rotate_hint(ns, 'This page isn’t working\nHTTP ERROR 429', hinted) == worker.ROTATE_HINT
	assert (
		worker._rotate_hint(ns, '[captcha solver: akamai stopped unsolved after 5s; handle it yourself]', {'x'})
		== worker.ROTATE_HINT
	)
	assert worker._rotate_hint(ns, '[captcha solver: solved recaptcha in 3s]', set()) == ''
	assert worker._rotate_hint({'page_info': lambda: host}, 'Access Denied', set()) == ''  # no rotate_proxy: no hint


async def test_the_hint_reaches_the_cell_output_once(tmp_path):
	async def rotate(country):
		return {'mode': 'managed', 'country': 'us', 'exitIp': '9.9.9.9'}

	repl = Repl(tmp_path, rotate_proxy=rotate)
	try:
		r = await repl.call('exec', "print('Access Denied')", 30)
		assert r['output'].count('[this page looks blocked for this IP') == 1 and 'help(rotate_proxy)' in r['output']
		r = await repl.call('exec', "print('Access Denied')", 30)
		assert 'looks blocked for this IP' not in r['output'] and 'rotate_proxy(' not in r['output']  # once per site
		r = await repl.call('exec', 'help(rotate_proxy)', 30)
		assert 'never in the middle of a login or checkout' in r['output']
	finally:
		await repl.close()


def test_the_block_hint_and_docstring_point_one_country_sites_at_that_country():
	# measured on 11 blocked sites: an exit in the site's own country turned Akamai blocks into passes (39% vs 8%)
	assert "rotate_proxy(country='xx')" in worker.ROTATE_HINT and 'serves one country' in worker.ROTATE_HINT
	doc = worker._rotate_proxy(lambda *a, **k: {}, cdp_first=False, rest=False).__doc__
	assert "rotate_proxy(country='ru')" in doc and 'serves' in doc
