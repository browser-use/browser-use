"""rotate_browser() / new_browser(): tools for a site that blocks the cloud browser even after rotate_proxy()."""

import pytest

from browser_use.browser import Browser
from browser_use.repl import worker


def _ns(**extra):
	pages = []
	ns = {'page_info': lambda: {'url': 'https://shop.example/item'}, 'goto_url': pages.append, 'wait_for_load': lambda: None}
	return {**ns, **extra}, pages


def test_the_block_hint_points_to_the_browser_tools_only_when_offered_and_once_per_site():
	ns = {'rotate_proxy': lambda c=None: {}, 'page_info': lambda: {'url': 'https://shop.example/'}}
	plain = worker._rotate_hint(dict(ns), 'Access Denied', set())
	assert plain == worker.ROTATE_HINT and 'rotate_browser' not in plain
	hinted: set = set()
	h = worker._rotate_hint({**ns, 'rotate_browser': lambda c=None: {}}, 'Access Denied', hinted)
	assert 'help(rotate_browser)' in h and h.endswith(']') and h.count('[') == 1
	assert worker._rotate_hint({**ns, 'rotate_browser': lambda c=None: {}}, 'Access Denied', hinted) == ''  # once per site
	assert 'help(new_browser)' in worker._rotate_hint({**ns, 'new_browser': lambda: {}}, 'Access Denied', set())
	assert worker._rotate_hint({**ns, 'rotate_browser': 1}, 'a normal page', set()) == ''  # no block, no hint


def test_rotate_browser_switches_the_daemon_and_reopens_the_page(monkeypatch):
	from browser_harness import helpers

	monkeypatch.setattr(helpers, 'NAME', 'bu-old')
	asked = []
	ns, pages = _ns()
	tools = worker._browser_tools(lambda kind, args: asked.append((kind, args)) or {'name': 'bu-new'}, ns, ['rotate'])
	assert set(tools) == {'rotate_browser'}
	assert tools['rotate_browser']() == {'browser': 'new', 'url': 'https://shop.example/item'}
	assert asked == [('browser', {'op': 'rotate', 'country': None})] and helpers.NAME == 'bu-new'
	assert pages == ['https://shop.example/item']
	assert 'At most once per site' in tools['rotate_browser'].__doc__ and 'never in the middle of a login' in tools['rotate_browser'].__doc__


def test_new_use_close_browser(monkeypatch):
	from browser_harness import helpers

	monkeypatch.setattr(helpers, 'NAME', 'bu-main')
	answers = {'open': {'browser': 1, 'name': 'bu-extra'}, 'close': {'closed': True}}
	ns, pages = _ns()
	t = worker._browser_tools(lambda kind, args: answers[args['op']], ns, ['multi'])
	assert set(t) == {'new_browser', 'use_browser', 'close_browser'}
	assert t['new_browser']('https://other.example/') == {'browser': 1, 'url': 'https://other.example/'} and helpers.NAME == 'bu-extra'
	assert t['use_browser'](0)['browser'] == 0 and helpers.NAME == 'bu-main'
	t['use_browser'](1)
	assert t['close_browser'](1) == {'browser': 0, 'open': [0]} and helpers.NAME == 'bu-main'
	with pytest.raises(ValueError):
		t['close_browser'](0)
	with pytest.raises(ValueError):
		t['use_browser'](5)


def test_sibling_keeps_the_settings_and_needs_a_cloud_browser():
	b = Browser(cloud_proxy_country_code='de', cloud_timeout=30, captcha_solver=False)
	s = b.sibling()
	assert (s.proxy, s.timeout, s.captcha_solver, s.use_cloud) == ('de', 30, False, True)
	assert b.sibling('ru').proxy == 'ru'
	with pytest.raises(RuntimeError):
		Browser('chromium').sibling()


@pytest.mark.asyncio
async def test_the_agent_caps_extra_browsers(monkeypatch):
	from browser_use import Agent
	from browser_use.agent import service

	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	started = []

	async def start(self):
		started.append(self)
		return {'BU_NAME': f'bu{len(started)}'}

	async def stop(self, downloads_dir=None):
		started.remove(self)
		return []

	monkeypatch.setattr(Browser, 'start', start)
	monkeypatch.setattr(Browser, 'stop', stop)
	agent = Agent('t', 'test', browser=Browser())
	for _ in range(service.MAX_EXTRA_BROWSERS):
		await agent._browser_op({'op': 'open'})
	with pytest.raises(RuntimeError, match='close_browser'):
		await agent._browser_op({'op': 'open'})
	await agent._browser_op({'op': 'close', 'browser': 1})
	await agent._stop_extra_browsers()
	assert started == []
