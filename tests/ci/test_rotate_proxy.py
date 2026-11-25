"""rotate_proxy(): a new exit IP for the same Browser Use cloud browser. The cloud API is faked; no browser."""

import pytest

from browser_use import Browser
from browser_use.browser import browser as browser_mod
from browser_use.browser.browser import cloud_browser_id
from browser_use.repl.session import Repl

ID = '27ea6d2b-e818-4bb6-ba44-bd743ee4bc7b'


def test_cloud_browser_id_from_cdp_url():
	assert cloud_browser_id(f'https://{ID}.cdp.browser-use.com') == ID
	assert cloud_browser_id(f'wss://{ID.upper()}.cdp.browser-use.com/devtools/browser/{ID}') == ID
	for url in (None, '', 'http://127.0.0.1:9222', f'https://{ID}.cdp.browser-use.com.evil.test', f'https://x.{ID}.example.com'):
		assert cloud_browser_id(url) is None, url


def test_only_a_cloud_browser_with_a_key_offers_it(monkeypatch):
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	assert Browser(cdp_url=f'https://{ID}.cdp.browser-use.com').can_rotate_proxy()
	assert not Browser(cdp_url='http://127.0.0.1:9222').can_rotate_proxy()
	assert not Browser('chromium').can_rotate_proxy()
	monkeypatch.delenv('BROWSER_USE_API_KEY')
	monkeypatch.setattr(browser_mod, 'browser_use_api_key', lambda **k: (_ for _ in ()).throw(RuntimeError('no key')))
	assert not Browser(cdp_url=f'https://{ID}.cdp.browser-use.com').can_rotate_proxy()


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
