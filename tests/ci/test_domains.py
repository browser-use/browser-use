"""Browser(allowed_domains=..., prohibited_domains=..., block_ip_addresses=..., strict_domains=...) (browser_use/domains.py).

The matcher cases are ported from 0.x tests/ci/security/test_domain_filtering.py and test_ip_blocking.py (browser-use
0.x main, SecurityWatchdog._is_url_allowed). The integration tests drive a real headless Chrome, one per enforcement
layer: the REPL helpers refuse (worker.py), the browser blocks (Guard), the cell sweep resets tabs (sweep), and an
Agent run on Browser('chromium') wires all of them."""

import asyncio
import http.server
import json
import threading
import time

import pytest
from pydantic_ai.messages import ModelRequest, ToolReturnPart
from websockets.sync.client import connect

from browser_use import Agent, Browser, domains
from browser_use.domains import DomainRules, Guard, disallowed_tabs, sweep
from browser_use.repl import Repl
from tests.ci.conftest import script


def test_a_prohibited_scheme_pattern_without_a_port_blocks_every_port():
	"""M22: prohibited_domains=['http://evil.test'] let http://evil.test:8080 through."""
	rules = DomainRules.of(prohibited=['http://evil.test'])
	assert rules.blocked('http://evil.test:8080/x') and rules.blocked('http://evil.test/')
	assert not rules.blocked('http://good.test:8080/')
	assert DomainRules.of(allowed=['http://ok.test']).blocked('http://ok.test:8080/')  # allowed: still the exact port


def test_the_0x_allowed_domains_env_var_raises_instead_of_being_ignored(monkeypatch):
	"""M21: BROWSER_USE_ALLOWED_DOMAINS was silently ignored: the browser went anywhere."""
	monkeypatch.setenv('BROWSER_USE_ALLOWED_DOMAINS', 'example.com')
	with pytest.raises(RuntimeError, match='BROWSER_USE_ALLOWED_DOMAINS environment variable was removed'):
		Browser('chromium')
	monkeypatch.setenv('BROWSER_USE_ALLOWED_DOMAINS', '')
	Browser('chromium')


def ok(url: str, allowed=(), prohibited=(), block_ips=False) -> bool:
	return DomainRules(tuple(allowed), tuple(prohibited), block_ips).blocked(url) is None


# 0.x TestUrlAllowlistSecurity


def test_userinfo_cannot_bypass_the_allowlist():
	a = ['example.com']
	assert not ok('https://example.com:password@malicious.com', a)
	assert not ok('https://example.com@malicious.com', a)
	assert not ok('https://example.com%20@malicious.com', a)
	assert not ok('https://example.com%3A@malicious.com', a)
	assert ok('https://user:password@example.com', a)


def test_glob_patterns():
	a = ['*.example.com']
	assert ok('https://sub.example.com', a) and ok('https://deep.sub.example.com', a)
	assert ok('https://example.com', a)  # *.example.com matches the domain itself, as in 0.x
	assert not ok('https://notexample.com', a) and not ok('https://example.org', a)
	a = ['*.google.com', 'https://wiki.org', 'https://good.com', 'https://*.test.com', 'chrome://version', 'brave://*']
	assert ok('https://google.com', a) and ok('https://www.google.com', a)
	assert not ok('https://evilgood.com', a)
	assert not ok('http://wiki.org', a) and ok('https://wiki.org', a)
	assert not ok('chrome://google.com', a) and not ok('chrome://abc.google.com', a)  # no scheme = http(s) only
	assert not ok('chrome://settings', a) and ok('chrome://version', a)
	assert not ok('chrome-extension://version/', a) and ok('brave://anything/', a)
	assert ok('about:blank', a) and ok('chrome://new-tab-page/', a) and ok('chrome://new-tab-page', a)
	assert not ok('https://allowed.example.com:password@notallowed.com', a)
	assert not ok('https://subdomain.example.com@evil.com', a)
	assert not ok('https://sub.example.com%20@malicious.org', a)
	assert not ok('https://anygoogle.com@evil.org', a)
	assert ok('https://www.test.com', a) and not ok('https://www.testx.com', a)


def test_glob_edge_cases():
	a = ['*.google.com', 'https://wiki.org']
	for url in ('https://notawiki.com', 'https://havewikipages.org', 'https://my-wiki-site.com', 'https://mygoogle.company.com'):
		assert not ok(url, a)
	a = ['*.google.com', '*.google.co.uk']
	assert ok('https://www.google.com', a) and ok('https://mail.google.co.uk', a)
	assert not ok('https://www.google.evil.com', a)


def test_www_is_added_only_for_one_dot_domains():
	a = ['example.com', 'test.org']
	assert ok('https://example.com', a) and ok('https://test.org', a)
	assert ok('https://www.example.com', a) and ok('https://www.test.org', a)
	assert not ok('https://mail.example.com', a) and not ok('https://sub.test.org', a)
	assert not ok('https://notexample.com', a) and not ok('https://www.notexample.com', a)
	a = ['example.co.uk', 'test.com.au', 'site.co.jp']
	assert all(ok(f'https://{d}', a) for d in a)
	assert not any(ok(f'https://www.{d}', a) for d in a)
	assert not ok('https://mail.example.co.uk', a) and not ok('https://api.test.com.au', a)
	a = ['mail.example.com', 'api.test.org']
	assert ok('https://mail.example.com', a) and ok('https://api.test.org', a)
	assert not ok('https://www.mail.example.com', a) and not ok('https://www.api.test.org', a)
	assert not ok('https://example.com', a) and not ok('https://test.org', a)
	a = ['https://example.com', 'http://test.org']  # a scheme pattern gets no www either
	assert ok('https://example.com/path', a) and ok('http://test.org/page', a)
	assert not ok('https://www.example.com', a) and not ok('http://www.test.org', a)


def test_prohibited_domains():
	p = ['example.com', 'test.org']
	assert not ok('https://example.com', prohibited=p) and not ok('https://www.example.com', prohibited=p)
	assert not ok('https://test.org', prohibited=p) and not ok('https://www.test.org', prohibited=p)
	assert not ok('https://mail.example.com', prohibited=p) and not ok('https://api.test.org', prohibited=p)  # 1.0
	assert ok('https://notexample.com', prohibited=p)
	p = ['*.example.com']
	assert not ok('https://example.com', prohibited=p) and not ok('https://mail.example.com', prohibited=p)
	assert ok('https://notexample.com', prohibited=p) and ok('chrome://abc.example.com', prohibited=p)
	p = ['https://wiki.org', 'brave://*']
	assert ok('http://wiki.org', prohibited=p)
	assert not ok('https://wiki.org', prohibited=p) and not ok('https://wiki.org/path', prohibited=p)
	assert not ok('brave://anything/', prohibited=p) and ok('chrome://settings', prohibited=p)
	p = ['*']
	for url in ('about:blank', 'chrome://new-tab-page/', 'chrome://new-tab-page', 'chrome://newtab/'):
		assert ok(url, prohibited=p)  # internal pages stay reachable even when everything is prohibited
	p = ['example.com']
	assert ok('https://example.com:password@malicious.com', prohibited=p)
	assert ok('https://example.com@malicious.com', prohibited=p)
	assert not ok('https://user:password@example.com', prohibited=p)
	p = ['Example.COM']
	assert not ok('https://example.com', prohibited=p) and not ok('https://WWW.EXAMPLE.COM', prohibited=p)
	assert not ok('https://mail.example.com', prohibited=p) and ok('https://example.co', prohibited=p)


def test_prohibited_is_ignored_when_an_allowlist_is_set():
	a, p = ['*.example.com'], ['https://example.com']
	assert ok('https://example.com', a, p) and ok('https://www.example.com', a, p) and ok('https://api.example.com', a, p)
	assert not ok('https://notexample.com', a, p)


def test_large_lists_and_sets_keep_patterns():
	"""0.x turned lists of 100+ into sets without pattern matching; 1.0 matches patterns at any size."""
	p = {f'blocked{i}.com' for i in range(100)} | {'*.google.com'}
	assert not ok('https://blocked0.com', prohibited=p) and not ok('https://www.blocked99.com', prohibited=p)
	assert not ok('https://mail.google.com', prohibited=p) and ok('https://blocked100.com', prohibited=p)
	a = [f'allowed{i}.com' for i in range(100)]
	assert ok('https://www.allowed0.com', a) and ok('https://allowed99.com', a) and not ok('https://example.com', a)


# 0.x test_ip_blocking.py


def test_block_ip_addresses():
	for url in (
		'http://180.1.1.1/supersafe.txt', 'https://8.8.8.8/', 'http://1.1.1.1:8080/api', 'http://192.168.1.1/',
		'http://10.0.0.1/', 'http://172.31.255.254/', 'http://127.0.0.1/', 'http://127.1.2.3/', 'https://8.8.8.8:443/',
		'https://9.10.11.12/path/to/file.html#anchor', 'http://[2001:db8::1]/', 'http://[::1]:8080/',
		'http://[0:0:0:0:0:0:0:1]/', 'https://[2001:db8::1]/api?key=value',
		'http://0x7f.1/', 'http://2130706433/', 'http://0177.0.0.1/', 'http://127.1/',  # forms the browser reads as IPv4
	):  # fmt: skip
		assert not ok(url, block_ips=True), url
		assert ok(url)  # off by default
	for url in ('https://example.com', 'http://localhost/', 'http://localhost:8080/api', 'https://123example.com',
				'https://server1.example.com', 'about:blank', 'chrome://new-tab-page/'):  # fmt: skip
		assert ok(url, block_ips=True), url


def test_ip_blocking_with_domain_lists():
	assert not ok('http://192.168.1.1/', ['example.com', '192.168.1.1'], block_ips=True)  # IPs first, even when allowed
	assert ok('https://example.com', ['example.com', '*.google.com'], block_ips=True)
	assert not ok('https://other.com', ['example.com'], block_ips=True)
	assert not ok('http://8.8.8.8/', prohibited=['example.com'], block_ips=True)
	assert ok('https://other.com', prohibited=['example.com'], block_ips=True)
	assert not ok('http://8.8.8.8/', prohibited=['example.com', '8.8.8.8'])
	assert ok('http://192.168.1.1/', prohibited=['example.com', '8.8.8.8'])


def test_invalid_urls_are_blocked():
	for url in ('not-a-url', '', 'http://', '://example.com', 'http://example.com:99999/'):
		assert not ok(url, ['example.com']), url


# Fixed or added in 1.0


def test_a_bare_prohibited_domain_covers_its_subdomains():
	"""0.x: prohibited_domains=['wikipedia.org'] let en.wikipedia.org through (a bare domain was itself plus www)."""
	p = ['wikipedia.org', 'mail.example.com']
	for url in ('https://en.wikipedia.org/wiki/X', 'https://m.en.wikipedia.org/', 'https://www.wikipedia.org/',
				'https://a.mail.example.com/', 'https://mail.example.com/'):  # fmt: skip
		assert not ok(url, prohibited=p), url
	for url in (
		'https://wikipedia.org.evil.com/',
		'https://notwikipedia.org/',
		'https://example.com/',
		'https://www.example.com/',
	):
		assert ok(url, prohibited=p), url
	assert ok('https://en.wikipedia.org/', ['wikipedia.org', 'en.wikipedia.org'])
	assert not ok('https://de.wikipedia.org/', ['wikipedia.org'])  # an allowlist entry is still itself plus www


def test_hosts_convert_as_chrome_does():
	"""Chrome converts hosts with UTS46/IDNA2008 (faß.de -> xn--fa-hia.de; Python's 'idna' codec says fass.de) and
	maps full-width dots and digits before reading an IPv4 address."""
	assert not ok('https://xn--fa-hia.de/', prohibited=['faß.de']) and not ok('https://faß.de/', prohibited=['faß.de'])
	assert ok('https://fass.de/', prohibited=['faß.de']) and not ok('https://fass.de/', ['faß.de'])
	assert ok('https://xn--fa-hia.de/', ['faß.de']) and ok('https://faß.de/', ['xn--fa-hia.de'])
	assert not ok('https://www.xn--bcher-kva.de/', prohibited=['https://*.bücher.de'])  # a scheme glob converts too
	assert not ok('https://www.bücher.de/', prohibited=['http*://*.xn--bcher-kva.de'])
	assert not ok('http://0x7f。1/', block_ips=True) and not ok('http://１２７.０.０.１/', block_ips=True)
	assert not ok('http://evil。com/', prohibited=['evil.com']) and ok('http://good。com/', ['good.com'])


def test_a_bare_ipv6_pattern_is_not_read_as_host_and_port():
	assert not ok('http://[::1]/', prohibited=['::1']) and not ok('http://[::1]:8080/', prohibited=['::1'])
	assert ok('http://[::1]:8080/', ['[::1]:8080']) and not ok('http://[::1]:9/', ['[::1]:8080'])
	assert ok('http://[2001:db8::1]/', ['2001:db8::1']) and not ok('http://[2001:db8::2]/', ['2001:db8::1'])


def test_scheme_patterns_compare_hosts_not_string_prefixes():
	"""0.x matched 'https://example.com' as a string prefix: https://example.com.evil.com and
	https://example.com@evil.com passed."""
	a = ['https://example.com']
	for url in ('https://example.com.evil.com/', 'https://example.com@evil.com/', 'https://example.com:8443/',
				'https://example.computer/'):  # fmt: skip
		assert not ok(url, a), url
	assert ok('https://example.com/', a) and ok('https://example.com:443/x', a)
	assert ok('https://example.com/docs/a', ['https://example.com/docs']) and not ok(
		'https://example.com/', ['https://example.com/docs']
	)
	glob = ['https://*.example.com/*']
	assert ok('https://a.example.com/x', glob) and not ok('https://evil.com/.example.com/', glob)


def test_dot_segments_cannot_escape_a_path_prefix():
	"""cubic: 'https://example.com/docs' matched https://example.com/docs/../admin, which the browser loads as /admin."""
	a = ['https://example.com/docs']
	for url in ('https://example.com/docs/../admin', 'https://example.com/docs/%2e%2E/admin', 'https://example.com/docs/.%2e/x',
				'https://example.com/docs\\..\\admin', 'https://example.com/docs/a/../../admin'):  # fmt: skip
		assert not ok(url, a), url
	assert ok('https://example.com/docs/a/../b', a) and ok('https://example.com/x/../docs/a', a)
	assert ok('https://example.com/docs/./a', ['https://example.com/docs/a'])
	assert not ok('https://example.com/a/../evil', prohibited=['https://example.com/evil'])


def test_lookalikes_case_trailing_dot_backslash_and_idn():
	a = ['example.com']
	for url in ('https://example.com.evil.com/', 'https://evil-example.com/', 'https://example.co/', 'https://xexample.com/',
				'https://evil.com\\@example.com/', 'https://evil.com\\.example.com/',
				'\x01https://evil.com\\@example.com/', ' \x1f\x00https://evil.com\\@example.com/\x7f '):  # fmt: skip
		assert not ok(url, a), url
	assert ok('HTTPS://EXAMPLE.COM/A', a) and ok('https://example.com./', a) and ok('https://ex%61mple.com/', a)
	assert not ok('https://example.com./', prohibited=a)  # the trailing dot is the same host for a blocklist too
	assert ok('https://xn--mnchen-3ya.de/', ['münchen.de']) and ok('https://münchen.de/', ['xn--mnchen-3ya.de'])
	assert ok('https://MÜNCHEN.de/', ['*.münchen.de']) and not ok('https://xn--mnchen-3ya.de.evil/', ['münchen.de'])


def test_ports_schemes_and_hostless_urls():
	assert ok('http://localhost:8080/', ['localhost']) and ok('http://localhost:3000/', ['localhost'])  # any port
	assert ok('http://localhost:8080/', ['localhost:8080']) and not ok('http://localhost:3000/', ['localhost:8080'])
	assert ok('http://localhost:8080/x', ['http://localhost:8080']) and not ok(
		'http://localhost:80801/', ['http://localhost:8080']
	)
	assert not ok('http://localhost:3000/', ['http://localhost'])  # a scheme pattern without a port: the default port
	assert ok('http://localhost:3000/', ['http://localhost:*'])
	assert ok('about:blank#x', ['example.com']) and ok('data:text/html,hi', ['example.com'])
	assert ok('blob:https://evil.com/0b1d', ['example.com'])  # 0.x: data: and blob: are always allowed
	for url in ('file:///etc/passwd', 'file://localhost/etc/passwd', 'javascript:alert(1)', 'view-source:https://example.com/'):
		assert not ok(url, ['example.com', 'localhost']), url
	assert not ok('ftp://example.com/', ['example.com'])  # no scheme in the pattern = http and https


def test_file_urls_blocked_under_every_rule():
	# Chrome reads file://localhost/<path> (and file://<any host>/) from the local disk, keeping that URL
	file_urls = ('file:///etc/passwd', 'file://localhost/etc/hosts', 'FILE://LOCALHOST/proc/self/environ', ' file://h/x')
	for rules in (
		DomainRules.of(['example.com']),
		DomainRules.of(prohibited=['evil.com']),
		DomainRules.of(block_ips=True),
		DomainRules.of(['file://*', 'localhost']),
	):
		for url in file_urls:
			assert (why := rules.blocked(url)) and 'is a file: URL or has no host' in why, (rules, url)
	assert DomainRules.of().blocked('file://localhost/etc/hosts') is None  # no rules: no restriction


def test_rules_messages_prompt_and_env():
	rules = DomainRules.of(['example.com', '*.example.org'])
	assert rules.blocked('https://evil.com/x') == 'blocked: evil.com is not in allowed_domains (example.com, *.example.org)'
	assert DomainRules.of(prohibited=['evil.com']).blocked('https://evil.com') == (
		'blocked: evil.com is in prohibited_domains (evil.com)'
	)
	assert (
		DomainRules.of(block_ips=True).blocked('http://10.0.0.1/')
		== 'blocked: 10.0.0.1 is an IP address (block_ip_addresses=True)'
	)
	assert 'example.com, *.example.org' in rules.prompt() and not DomainRules.of().prompt()
	assert DomainRules.from_json(rules.to_json()) == rules and not DomainRules.from_json(None)
	assert not DomainRules.of([], []) and not DomainRules.of(None, None)  # [] is no restriction, as in 0.x
	with pytest.raises(TypeError, match='list of domain patterns'):
		DomainRules.of('example.com')  # a bare string would be read as single characters
	with pytest.raises(TypeError, match='non-empty string'):
		DomainRules.of(['example.com', ''])


def test_a_tab_before_its_first_navigation_is_blank_not_disallowed():
	"""A new tab reports url '': it must not land in the start snapshot (sweep would then never reset it)."""
	targets = [
		{'type': 'page', 'targetId': 'new', 'url': ''},
		{'type': 'page', 'targetId': 'evil', 'url': 'https://evil.com/'},
		{'type': 'iframe', 'targetId': 'frame', 'url': 'https://evil.com/'},
	]
	tabs = disallowed_tabs(lambda method, **_: {'targetInfos': targets}, RULES)
	assert tabs == {'evil': ('https://evil.com/', 'blocked: evil.com is not in allowed_domains (allowed.localhost)')}


def test_a_kept_tab_is_reset_once_it_navigates():
	"""Browser('chrome'): a tab you had open on a disallowed page is exempt only while it still shows that page; JS in
	it navigating elsewhere must not stay exempt for the whole run."""
	urls = {'kept': 'https://other.com/start', 'agent': 'https://evil.com/'}
	sent = []

	def cdp(method, session_id=None, **params):
		sent.append((method, params.get('targetId') or params.get('url')))
		if method == 'Target.getTargets':
			return {'targetInfos': [{'type': 'page', 'targetId': t, 'url': u} for t, u in urls.items()]}
		return {'sessionId': 's'}

	keep = {'kept': 'https://other.com/start'}
	sweep(cdp, RULES, keep)
	assert ('Target.attachToTarget', 'agent') in sent and ('Target.attachToTarget', 'kept') not in sent
	sent.clear()
	urls['kept'] = 'https://evil.com/navigated'
	notes = sweep(cdp, RULES, keep)
	assert ('Target.attachToTarget', 'kept') in sent and len(notes) == 2


def test_attach_mode_sweeps_only_the_agents_tabs(monkeypatch, tmp_path):
	"""Browser('chrome'): the sweep resets the tabs the agent created (worker.py writes BU_TABS_FILE), the tab the daemon
	is attached to, and popups they opened; never a tab you opened yourself on a site outside the list."""
	from browser_use.browser import browser as module

	targets = {
		'created': ('https://evil.com/1', None),
		'attached': ('https://evil.com/2', None),
		'popup': ('https://evil.com/3', 'created'),
		'popup_of_popup': ('https://evil.com/4', 'popup'),
		'yours': ('https://mail.example.org/draft', None),
	}
	reset = []

	def cdp(name, method, session_id=None, **params):
		if method == 'Target.getTargets':
			infos = [{'type': 'page', 'targetId': t, 'url': u, **({'openerId': o} if o else {})} for t, (u, o) in targets.items()]
			return {'targetInfos': infos}
		if method == 'Target.attachToTarget':
			reset.append(params['targetId'])
		return {'sessionId': 's'}

	monkeypatch.setattr(module, '_daemon_cdp', cdp)
	monkeypatch.setattr(module, '_daemon_request', lambda name, req: {'targetId': 'attached'})
	browser = Browser('chrome', allowed_domains=['allowed.localhost'])
	browser._tabs_file = str(tmp_path / 'tabs')
	(tmp_path / 'tabs').write_text('created\n')
	notes = browser._sweep()
	assert sorted(reset) == ['attached', 'created', 'popup', 'popup_of_popup'] and len(notes) == 4
	reset.clear()
	Browser('chromium', allowed_domains=['allowed.localhost'])._sweep()  # a browser of our own: every tab
	assert 'yours' in reset


async def test_the_worker_records_the_tabs_it_creates(daemon, tmp_path):
	"""BU_TABS_FILE: every Target.createTarget the worker sends (new_tab included) appends the new tab's id."""
	tabs = tmp_path / 'tabs'
	repl = Repl(tmp_path, {**daemon, 'BU_DOMAINS': RULES.to_json(), 'BU_TABS_FILE': str(tabs)})
	try:
		r = await repl.call(
			'exec', 'a = new_tab(); b = cdp("Target.createTarget", url="about:blank")["targetId"]; print(a, b)', 30
		)
		assert r['error'] is None, r['error']
	finally:
		await repl.close()
	assert set(tabs.read_text().split()) == set(r['output'].split())  # new_tab also attaches (switch_tab)


async def test_attach_mode_sweeps_a_tab_the_agent_used_and_left_in_one_cell(daemon, site, tmp_path, monkeypatch):
	"""r266-tech, PR comment 11-06: in one cell the agent switched to your existing tab A, sent it to a disallowed page,
	and switched on to B. Only created tabs and the tab attached at the end of the cell were swept, so A stayed on the
	disallowed page. A tab you opened (C) and the agent never touched stays as it is."""
	from functools import partial

	from browser_use.browser.browser import _daemon_cdp

	cdp = partial(_daemon_cdp, daemon['BU_NAME'])
	a, b, c = (
		cdp('Target.createTarget', url=url)['targetId']
		for url in (f'{site["allowed"]}/a', f'{site["allowed"]}/b', f'{site["evil"]}/c')
	)
	tabs = tmp_path / 'tabs'
	repl = Repl(tmp_path, {**daemon, 'BU_DOMAINS': RULES.to_json(), 'BU_TABS_FILE': str(tabs)})
	try:
		code = f'switch_tab({a!r}); js("location.href = {site["evil"] + "/escaped"!r}"); wait(1); switch_tab({b!r}); print(page_info()["url"])'
		r = await repl.call('exec', code, 30)
		assert r['error'] is None and '/b' in r['output'], r
		monkeypatch.setenv('BU_NAME', daemon['BU_NAME'])
		browser = Browser('chrome', allowed_domains=['allowed.localhost'])
		browser._tabs_file, browser._user_tabs = str(tabs), {}
		notes = await asyncio.to_thread(browser._sweep)
		for _ in range(50):  # the reset commits shortly after Page.navigate returns
			urls = {t['targetId']: t['url'] for t in cdp('Target.getTargets')['targetInfos']}
			if urls[a] == 'about:blank':
				break
			await asyncio.sleep(0.1)
	finally:
		await repl.close()
		for tab in (a, b, c):  # the browser is shared with later tests
			cdp('Target.closeTarget', targetId=tab)
	assert urls[a] == 'about:blank' and len(notes) == 1 and a[:8] in notes[0]
	assert urls[c] == f'{site["evil"]}/c' and urls[b] == f'{site["allowed"]}/b'


async def test_the_kept_tabs_are_taken_once_per_browser(monkeypatch):
	"""Browser('chrome') runs _start() on every start() (each run, each reattach): a tab the agent left on a disallowed
	page (a late redirect after its last cell) must not become exempt in the next run."""
	browser = Browser('chrome', allowed_domains=['allowed.localhost'])
	snapshots = iter([{'yours': 'https://other.com/'}, {'yours': 'https://other.com/', 'agent': 'https://evil.com/'}])

	async def start():
		return {}

	monkeypatch.setattr(browser, '_start', start)
	monkeypatch.setattr(browser, '_disallowed_tabs', lambda: next(snapshots))
	await browser.start()
	await browser.start()
	assert browser._user_tabs == {'yours': 'https://other.com/'}


async def test_only_your_open_chrome_keeps_its_tabs_on_disallowed_pages(monkeypatch):
	"""cubic: every mode took the start snapshot, so Browser(cdp_url=...) never reset a tab that was already on a
	disallowed page. Only Browser('chrome') attached to your open Chrome keeps your tabs."""
	urls = {'theirs': 'https://evil.com/'}
	reset = []

	def cdp(method, session_id=None, **params):
		if method == 'Target.getTargets':
			return {'targetInfos': [{'type': 'page', 'targetId': t, 'url': u} for t, u in urls.items()]}
		if method == 'Target.attachToTarget':
			reset.append(params['targetId'])
		return {'sessionId': 's'}

	async def start():
		return {}

	for browser, kept in ((Browser(cdp_url='http://127.0.0.1:9', allowed_domains=['allowed.localhost']), False),
						  (Browser('chrome', allowed_domains=['allowed.localhost']), True)):  # fmt: skip
		monkeypatch.setattr(browser, '_start', start)
		monkeypatch.setattr(browser, '_cdp', lambda: cdp)
		monkeypatch.setattr(browser, '_touched_tabs', lambda: {'theirs'})
		reset.clear()
		await browser.start()
		browser._sweep()
		assert reset == ([] if kept else ['theirs'])


def test_browser_takes_domain_options_in_every_mode():
	for b in (
		Browser(allowed_domains=['example.com']),
		Browser('chromium', prohibited_domains=['evil.com']),
		Browser('chrome', block_ip_addresses=True),
		Browser(cdp_url='http://127.0.0.1:9222', allowed_domains={'example.com'}),
	):
		assert b.domains
	assert not Browser().domains


def test_system_prompt_line_only_with_restrictions(tmp_path):
	def prompt(browser):
		agent = Agent('t', 'test', browser=browser, workspace=tmp_path)
		agent._build()
		return [i.instruction for i in agent._agent._instructions if isinstance(i.instruction, str)][0]

	plain = prompt(Browser('chromium'))
	restricted = prompt(Browser('chromium', allowed_domains=['example.com']))
	assert (
		restricted
		== f'{plain}\nThe browser may only open these domains: example.com. Other navigation is blocked by the browser; do not try to get around it.'
	)
	attached = prompt(Browser('chrome', allowed_domains=['example.com']))  # no browser-level block in attach mode
	assert attached.endswith('example.com. Other pages are reset to about:blank after each step; do not try to get around it.')
	# Live: 'must not open these domains: evil.com. Other navigation is blocked by the browser' told the model every
	# other site was blocked too
	prohibited = prompt(Browser('chromium', prohibited_domains=['evil.com'], block_ip_addresses=True))
	assert prohibited.endswith(
		'must not open these domains: evil.com. IP-address URLs are blocked. The browser blocks them; do not try to get around it.'
	)
	assert prompt(Browser('chrome', prohibited_domains=['evil.com'])).endswith(
		'evil.com. A tab that opens one is reset to about:blank after each step; do not try to get around it.'
	)


# Against a real Chrome: one test per layer, each failing without its layer


class Site(http.server.BaseHTTPRequestHandler):
	"""allowed.localhost and evil.localhost (Chrome resolves *.localhost to loopback); records every request."""

	hits: list[str] = []

	def log_message(self, *args):
		pass

	def do_GET(self):
		host, port = self.headers['Host'].split(':')
		Site.hits.append(f'{host}{self.path}')
		path = self.path.split('?')[0]
		if path in PROBE:  # strict_domains: every kind of request a page on an allowed host can send to evil
			body = PROBE[path].replace('EVIL', f'http://evil.localhost:{port}')
			self.send_response(200)
			self.send_header('Content-Type', 'text/html' if path == '/probe' else 'text/javascript')
			self.end_headers()
			self.wfile.write(body.encode())
			return
		if self.path == '/redirect':
			self.send_response(302)
			self.send_header('Location', f'http://evil.localhost:{port}/redirected')
			self.end_headers()
			return
		evil = f'http://evil.localhost:{port}'
		body = {
			'/': f'<a id=link href="{evil}/clicked">x</a><a id=blank target=_blank href="{evil}/blank">b</a>',
			'/meta': f'<meta http-equiv=refresh content="0;url={evil}/meta">',
		}.get(self.path, f'<title>{host}{self.path}</title>')
		self.send_response(200)
		self.send_header('Content-Type', 'text/html')
		self.end_headers()
		self.wfile.write(body.encode())

	do_POST = do_GET  # sendBeacon


# ?<run> keeps the service worker of one run apart from another's (a scope of its own installs it again)
PROBE = {
	'/probe': """<link rel=stylesheet href="EVIL/css"><img src="EVIL/img"><script src="EVIL/script"></script>
<iframe src="EVIL/iframe"></iframe><script>
const run = location.search.slice(1)
fetch('EVIL/fetch').catch(() => 0)
fetch('/redirect').catch(() => 0)
const xhr = new XMLHttpRequest(); xhr.open('GET', 'EVIL/xhr'); xhr.send()
navigator.sendBeacon('EVIL/beacon', 'x')
new Worker('/worker.js')
navigator.serviceWorker.register('/sw.js?' + run, {scope: '/' + run + '/'})
</script>""",
	'/worker.js': "fetch('EVIL/worker')",
	'/sw.js': "self.oninstall = e => e.waitUntil(fetch('EVIL/sw').catch(() => 0))",
}
PROBED = ('/css', '/img', '/script', '/iframe', '/fetch', '/redirected', '/xhr', '/beacon', '/worker', '/sw')


@pytest.fixture(scope='module')
def site():
	server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Site)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	port = server.server_address[1]
	yield {'allowed': f'http://allowed.localhost:{port}', 'evil': f'http://evil.localhost:{port}'}
	server.shutdown()


def evil_hits() -> list[str]:
	return [h for h in Site.hits if h.startswith('evil.')]


RULES = DomainRules.of(['allowed.localhost'])


def page_urls(chrome) -> list[str]:
	with connect(chrome['ws'], max_size=None) as c:
		c.send('{"id": 1, "method": "Target.getTargets"}')
		return [t['url'] for t in json.loads(c.recv())['result']['targetInfos'] if t['type'] == 'page']


async def test_helpers_refuse_disallowed_urls(daemon, site, tmp_path):
	"""Layer 1 (worker.py check_url): goto_url, new_tab, cdp('Page.navigate' / 'Target.createTarget') and http_get raise
	before anything navigates; new_tab opens no empty tab first."""
	Site.hits.clear()
	repl = Repl(tmp_path, {**daemon, 'BU_DOMAINS': RULES.to_json()})
	try:
		r = await repl.call('exec', f'goto_url({site["allowed"] + "/ok"!r}); wait_for_load(); page_info()["url"]', 30)
		assert r['error'] is None and '/ok' in r['output']
		r = await repl.call('exec', 'n = len(list_tabs())', 30)
		for code in (
			f'goto_url({site["evil"]!r})',
			f'new_tab({site["evil"] + "/tab"!r})',
			f'cdp("Page.navigate", url={site["evil"]!r})',
			f'cdp("Target.createTarget", url={site["evil"]!r})',
			f'http_get({site["evil"]!r})',
			f'http_get({site["allowed"] + "/redirect"!r})',  # each redirect hop is checked before it is followed
			f'import urllib.request; urllib.request.urlopen({site["allowed"] + "/redirect"!r})',
		):
			r = await repl.call('exec', code, 30)
			assert (
				r['error']
				and 'PermissionError: blocked: evil.localhost is not in allowed_domains (allowed.localhost)' in r['error']
			), code
			assert r['stats']['events'] == {'domain_blocked': 1}
		# http_get took the opener to call (_urlopen=): a fresh one followed the redirect to evil unchecked
		redirect = site['allowed'] + '/redirect'
		r = await repl.call(
			'exec', f'import urllib.request; http_get({redirect!r}, _urlopen=urllib.request.build_opener().open)', 30
		)
		assert r['error'], r['output']
		r = await repl.call('exec', 'len(list_tabs()) == n', 30)
		assert r['output'].strip() == 'True'
	finally:
		await repl.close()
	assert evil_hits() == []


def test_mcp_http_get_checks_every_redirect_and_stays_local(site, monkeypatch):
	"""NET-4: --mcp with allowed_domains checked only http_get's first URL, so a redirect from an allowed host fetched
	any host, and with BROWSER_USE_API_KEY set the URL and headers went to the fetch-use proxy instead."""
	import socket

	import fetch_use

	from browser_use.mcp import cli_mcp

	real = socket.getaddrinfo  # Windows' resolver has no *.localhost (Chrome's, used by the other site tests, does)
	monkeypatch.setattr(socket, 'getaddrinfo', lambda h, *a, **k: real('127.0.0.1' if h.endswith('.localhost') else h, *a, **k))
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'bu_test')
	monkeypatch.setattr(fetch_use, 'fetch_sync', lambda *a, **k: pytest.fail('http_get went through fetch-use'))
	mcp = cli_mcp.CLIMCPServer(own_browser=True, allowed_domains=['allowed.localhost'])
	Site.hits.clear()
	out, failed = mcp._execute(f'print(http_get({site["allowed"] + "/ok"!r}))', connect=False)
	assert not failed and '<title>allowed.localhost/ok</title>' in out, out
	out, failed = mcp._execute(f'http_get({site["allowed"] + "/redirect"!r})', connect=False)
	assert failed and 'PermissionError: blocked: evil.localhost is not in allowed_domains' in out, out
	assert evil_hits() == []


async def test_guard_blocks_navigations_the_helpers_never_see(chrome, daemon, site, tmp_path):
	"""Layer 2 (Guard): link clicks, redirects, target=_blank, window.open, meta refresh, JS location and a raw
	Target.createTarget(url=...) never reach the disallowed host."""
	Site.hits.clear()
	guard = Guard(chrome['ws'], RULES)
	guard.start()
	repl = Repl(tmp_path, daemon)  # no BU_DOMAINS: the helpers do not check, only the browser does
	evil, allowed = site['evil'], site['allowed']
	try:
		cells = [
			f'goto_url({allowed + "/"!r}); wait_for_load(); js("document.getElementById(\'link\').click()"); wait(1)',
			f'goto_url({allowed + "/redirect"!r}); wait(1)',
			f'goto_url({allowed + "/"!r}); wait_for_load(); '
			"cdp('Runtime.evaluate', expression=\"document.getElementById('blank').click()\", userGesture=True); wait(1)",
			f'cdp("Runtime.evaluate", expression="window.open({evil + "/popup"!r})", userGesture=True); wait(1)',
			f'goto_url({allowed + "/meta"!r}); wait(1.5)',
			f'goto_url({allowed + "/"!r}); wait_for_load(); js("location.href = {evil + "/js"!r}"); wait(1)',
			f'cdp("Target.createTarget", url={evil + "/created"!r}); wait(1)',
		]
		for code in cells:
			r = await repl.call('exec', code, 30)
			assert r['error'] is None, (code, r['error'])
		notices, blocks = guard.take()
	finally:
		await repl.close()
		guard.close()
	assert evil_hits() == []
	assert blocks == 7, notices  # the error pages the blocks left were reset silently: no second count
	assert not [u for u in page_urls(chrome) if 'evil.' in u]
	assert notices[0].startswith(
		'[blocked: evil.localhost is not in allowed_domains (allowed.localhost). The browser did not load'
	)
	assert any(h.startswith('allowed.localhost/') for h in Site.hits)  # allowed pages still load through the guard


async def test_sweep_resets_tabs_left_on_a_disallowed_page(chrome, daemon, site, tmp_path):
	"""Layer 3 (sweep): a tab that shows a disallowed page after a cell goes to about:blank; a tab in keep (open on
	such a page before the browser started: yours) is left alone."""
	from functools import partial

	from browser_use.browser.browser import _daemon_cdp

	cdp = partial(_daemon_cdp, daemon['BU_NAME'])
	before = {
		t['targetId']: t['url'] for t in cdp('Target.getTargets')['targetInfos'] if RULES.blocked(t['url'])
	}  # earlier tests'
	repl = Repl(tmp_path, daemon)
	try:
		r = await repl.call('exec', f'new_tab({site["evil"] + "/stay"!r}); wait_for_load(); current_tab()["targetId"]', 30)
		tab = r['output'].strip()
		mine = await repl.call('exec', f'new_tab({site["evil"] + "/mine"!r}); wait_for_load(); current_tab()["targetId"]', 30)
		keep = {**before, mine['output'].strip(): f'{site["evil"]}/mine'}
		notes = await asyncio.to_thread(sweep, cdp, RULES, keep)
		urls = page_urls(chrome)
	finally:
		await repl.close()
	assert notes == [
		f'[blocked: evil.localhost is not in allowed_domains (allowed.localhost). Tab {tab[:8]} showed it; browser-use '
		'navigated that tab to about:blank]'
	]
	assert 'about:blank' in urls and f'{site["evil"]}/mine' in urls and f'{site["evil"]}/stay' not in urls


async def test_agent_on_chromium_enforces_every_layer(chrome_binary, site, tmp_path):
	"""Browser('chromium', allowed_domains=...) end to end: the prompt line, the helper refusal, the browser block on a
	link click with its notice in the cell output, the sweep, and telemetry's count."""
	Site.hits.clear()
	evil, allowed = site['evil'], site['allowed']
	model, seen = script(
		('python', {'code': f'new_tab({allowed + "/"!r}); wait_for_load(); print(page_info()["url"])'}),
		('python', {'code': f'new_tab({evil + "/direct"!r})'}),
		('python', {'code': 'js("document.getElementById(\'link\').click()"); wait(1); print("CELL-OUTPUT")'}),
		('python', {'code': 'print([t["url"] for t in list_tabs()])'}),
		('finish', {'success': True, 'result': 'done'}),
	)
	browser = Browser('chromium', headless=True, executable_path=chrome_binary, allowed_domains=['allowed.localhost'])
	agent = Agent('Visit pages', model, browser=browser, workspace=tmp_path)
	captured = []
	agent._capture = lambda result, session, *a: captured.append(session.stats)  # type: ignore[method-assign]
	result = await agent.run()
	assert result.status == 'completed', result.error
	first = next(m for m in seen[0] if isinstance(m, ModelRequest))
	assert 'The browser may only open these domains: allowed.localhost.' in (first.instructions or '')
	returns = [
		p.content for m in result.messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart)
	]
	assert 'allowed.localhost' in str(returns[0])
	assert 'PermissionError: blocked: evil.localhost is not in allowed_domains' in str(returns[1])
	assert '[blocked: evil.localhost is not in allowed_domains (allowed.localhost). The browser did not load' in str(returns[2])
	assert str(returns[2]).index('[blocked') < str(returns[2]).index('CELL-OUTPUT')  # notices before the cell's output
	assert 'evil.localhost' not in str(returns[3])
	assert evil_hits() == []
	assert captured[0].events['domain_blocked'] == 2  # helper refusal + browser block (its error page reset silently)
	assert browser._guard is None  # stopped with the browser


async def test_guard_resets_a_tab_that_commits_without_a_request_it_saw(chrome, daemon, site, tmp_path):
	"""A page can commit with no request the guard intercepts (a speculation-rules prefetch, which Chrome fetches in a
	context Fetch does not see; the back/forward cache): the guard navigates the tab to about:blank as soon as its URL
	changes to a disallowed one. Simulated by a guard that lets every request through."""

	class Blind(Guard):
		def _handle(self, msg):
			if msg.get('method') == 'Fetch.requestPaused':
				self._send('Fetch.continueRequest', requestId=msg['params']['requestId'])
				return
			super()._handle(msg)

	guard = Blind(chrome['ws'], RULES)
	guard.start()
	repl = Repl(tmp_path, daemon)
	try:
		code = f'goto_url({site["allowed"] + "/"!r}); wait_for_load(); js("location.href = {site["evil"] + "/committed"!r}"); wait(1)'
		r = await repl.call('exec', f'{code}; print(page_info()["url"])', 30)
		assert r['error'] is None, r['error']
		notices, blocks = guard.take()
	finally:
		await repl.close()
		guard.close()
	assert r['output'].strip() == 'about:blank'
	assert blocks == 1 and notices[0].endswith('/committed; browser-use navigated it to about:blank]'), notices


def test_guard_start_failure_raises():
	guard = Guard('ws://127.0.0.1:9/devtools/browser/x', RULES)
	with pytest.raises(RuntimeError, match='Domain restrictions could not start'):
		guard.start()
	time.sleep(0.1)
	assert not guard._thread.is_alive()


async def test_guard_reconnects_after_its_connection_drops(chrome, daemon, site, tmp_path):
	"""Chrome drops a closed connection's interception; the guard connects again and blocks again."""
	Site.hits.clear()
	guard = Guard(chrome['ws'], RULES)
	guard.start()
	repl = Repl(tmp_path, daemon)
	try:
		first = guard._ws
		first.close()  # as a network drop would: the guard was not closed
		for _ in range(50):
			if guard._ws is not first and guard._ws is not None and guard.pages:
				break
			await asyncio.sleep(0.1)
		r = await repl.call(
			'exec',
			f'goto_url({site["allowed"] + "/"!r}); wait_for_load(); js("location.href = {site["evil"] + "/again"!r}"); wait(1)',
			30,
		)
		assert r['error'] is None, r['error']
		_, blocks = guard.take()
	finally:
		await repl.close()
		guard.close()
	assert guard._ws is None and blocks == 1 and evil_hits() == []


# strict_domains=True: every request, private addresses, fail closed


def test_strict_blocks_private_and_local_addresses_unless_allowed_domains_names_them():
	"""An agent with only prohibited_domains could fetch the cloud metadata service (169.254.169.254) or the host's own
	services; strict_domains blocks them, in every spelling, and only a pattern that names the host lets one through."""
	strict = DomainRules.of(prohibited=['evil.com'], strict=True)
	for url in (
		'http://169.254.169.254/latest/meta-data/',
		'http://[::ffff:169.254.169.254]/',  # IPv4-mapped IPv6
		'http://[fd00:ec2::254]/',
		'http://0xa9.0xfe.0xa9.0xfe/',  # 169.254.169.254 as Chrome reads it
		'http://127.0.0.1:8080/',
		'http://[::1]/',
		'http://10.0.0.1/',
		'http://192.168.1.1/',
		'http://100.64.0.1/',  # shared (CGNAT)
		'http://0.0.0.0/',
		'http://localhost/',
		'http://app.localhost/',
		'http://metadata/',  # single label: the local search domain resolves it
		'http://metadata.google.internal/',
		'http://printer.local/',
		'http://router.home.arpa/',
		'ws://127.0.0.1/',
		'http://[64:ff9b::a00:1]/',  # NAT64: 10.0.0.1 through the network's NAT64 gateway
		'http://[64:ff9b::169.254.169.254]/',
		'http://[64:ff9b:1::a00:1]/',  # local-use NAT64 prefix
		'http://[::a9fe:a9fe]/',  # IPv4-compatible
	):
		assert strict.blocked(url) == (
			f'blocked: {parse_host(url)} is a private or local address (strict_domains=True; allowed_domains can name it)'
		), url
	assert strict.blocked('https://8.8.8.8/') is None and strict.blocked('https://example.org/') is None
	assert strict.blocked('http://[64:ff9b::808:808]/') is None  # NAT64 of a public address
	assert strict.blocked('http://a\x00.1/') is None  # a NUL byte: Chrome refuses the host; reading it raised ValueError
	assert strict.blocked('chrome://settings') is None  # not a network request
	assert not DomainRules.of(prohibited=['evil.com']).blocked('http://169.254.169.254/')  # unchanged without strict
	named = DomainRules.of(['example.com', 'localhost:8080', '*.corp.internal'], strict=True)
	assert named.blocked('http://localhost:8080/') is None and named.blocked('https://wiki.corp.internal/') is None
	assert (
		named.blocked('http://localhost:9000/')
		== 'blocked: localhost is not in allowed_domains (example.com, localhost:8080, *.corp.internal)'
	)
	assert DomainRules.of(['http*://*'], strict=True).blocked('http://169.254.169.254/')  # a catch-all names no host
	assert DomainRules.from_json(named.to_json()) == named and DomainRules.of(strict=True)
	assert DomainRules.of(strict=True).prompt() == (
		'The browser blocks every request to private or local addresses, including the requests pages make (fetch, '
		'images, iframes); do not try to get around it.'
	)
	assert named.prompt().endswith(
		'The browser blocks every request to other hosts and to private or local addresses, including the requests pages '
		'make (fetch, images, iframes); do not try to get around it.'
	)


def parse_host(url: str) -> str:
	from browser_use.domains import parse_url

	u = parse_url(url)
	assert u is not None
	return u.host


def test_strict_domains_options():
	assert Browser('chromium', allowed_domains=['example.com'], strict_domains=True).domains.strict
	assert Browser(cdp_url='http://127.0.0.1:9222', strict_domains=True).domains  # alone: private addresses only
	assert Browser('chrome', profile='Work', strict_domains=True).domains.strict
	with pytest.raises(ValueError, match=r"Browser\('chrome'\) \(your open Chrome\) does not take strict_domains=True"):
		Browser('chrome', allowed_domains=['example.com'], strict_domains=True)
	with pytest.raises(TypeError, match='strict_domains must be True or False'):
		Browser('chromium', strict_domains='yes')  # type: ignore[arg-type]


async def probe(guard: Guard, repl: Repl, url: str, until) -> list[str]:
	"""Open url in the agent's tab and collect the guard's notices until until(notices) or 10 s."""
	r = await repl.call('exec', f'goto_url({url!r}); wait_for_load(); print(page_info()["url"])', 30)
	assert r['error'] is None and url[:20] in r['output'], r
	notices, deadline = [], time.monotonic() + 10
	while not until(notices) and time.monotonic() < deadline:
		await asyncio.sleep(0.2)
		notices += guard.take()[0]
	await repl.call('exec', 'goto_url("about:blank")', 30)
	return notices


async def test_strict_guard_fails_every_request_to_a_disallowed_host(chrome, daemon, site, tmp_path, monkeypatch):
	"""Without strict_domains a page on an allowed host loads images, scripts, iframes, fetch/XHR, beacons and worker
	requests from any host (the default, unchanged). With it, the browser fails each of them, also from a dedicated
	worker, a service worker and a redirect hop, and the allowed host's own requests still load."""
	monkeypatch.setattr(domains, 'NOTICES_PER_CELL', 50)
	allowed = site['allowed']
	repl = Repl(tmp_path, daemon)
	try:
		Site.hits.clear()
		loose = Guard(chrome['ws'], RULES)
		loose.start()
		try:
			await probe(loose, repl, f'{allowed}/probe?loose', lambda _: {'/img', '/fetch', '/iframe'} <= evil_paths())
		finally:
			loose.close()
		assert {'/img', '/fetch', '/iframe'} <= evil_paths()  # what strict_domains is for

		await asyncio.sleep(1)  # the loose run's stragglers
		Site.hits.clear()
		strict = Guard(chrome['ws'], DomainRules.of(['allowed.localhost'], strict=True))
		strict.start()
		try:
			notices = await probe(
				strict, repl, f'{allowed}/probe?strict', lambda n: all(any(f'{p}]' in x for x in n) for p in PROBED)
			)
		finally:
			strict.close()
	finally:
		await repl.close()
	assert evil_hits() == []
	for path in PROBED:
		assert (
			f'[blocked: evil.localhost is not in allowed_domains (allowed.localhost). The browser did not load {site["evil"]}{path}]'
			in notices
		), path
	assert {'allowed.localhost/probe?strict', 'allowed.localhost/worker.js', 'allowed.localhost/sw.js?strict'} <= set(Site.hits)


def evil_paths() -> set[str]:
	return {'/' + h.split('/', 1)[1] for h in evil_hits()}


async def test_strict_guard_blocks_private_addresses_from_any_page(chrome, daemon, site, tmp_path):
	"""With only prohibited_domains, a page (here a data: URL, always allowed) cannot reach 127.0.0.1 or the metadata
	service: the browser fails the request before it is sent."""
	port = site['allowed'].rsplit(':', 1)[1]
	page = f'data:text/html,<img src="http://127.0.0.1:{port}/private"><img src="http://169.254.169.254/latest/meta-data/">'
	Site.hits.clear()
	guard = Guard(chrome['ws'], DomainRules.of(prohibited=['evil.localhost'], strict=True))
	guard.start()
	repl = Repl(tmp_path, daemon)
	try:
		notices = await probe(guard, repl, page, lambda n: len(n) >= 2)
	finally:
		await repl.close()
		guard.close()
	assert not [h for h in Site.hits if h.startswith('127.0.0.1')]
	assert sorted(notices) == [
		f'[blocked: 127.0.0.1 is a private or local address (strict_domains=True; allowed_domains can name it). The '
		f'browser did not load http://127.0.0.1:{port}/private]',
		'[blocked: 169.254.169.254 is a private or local address (strict_domains=True; allowed_domains can name it). The '
		'browser did not load http://169.254.169.254/latest/meta-data/]',
	]


async def test_strict_runs_no_cell_while_the_request_filter_is_down(chrome, site, tmp_path, monkeypatch):
	"""Chrome stops intercepting the moment the guard's connection closes: with strict_domains the REPL refuses every
	cell until it is back, then says requests went unfiltered meanwhile."""
	import browser_use.browser.browser as browser_module

	monkeypatch.setattr(browser_module, 'GUARD_START_S', 1.0)
	browser = Browser(cdp_url=chrome['http'], allowed_domains=['allowed.localhost'], strict_domains=True)
	env = await browser.start()
	repl = Repl(tmp_path, env, before_cell=browser.before_cell, after_cell=browser.after_cell)
	ran = tmp_path / 'ran'
	try:
		guard = browser._guard
		assert guard is not None and guard.connected.is_set()
		real, guard.ws_url = guard.ws_url, 'ws://127.0.0.1:9/devtools/browser/x'  # its reconnects fail
		guard._ws.close()
		for _ in range(50):
			if not guard.connected.is_set():
				break
			await asyncio.sleep(0.1)
		r = await repl.call('exec', f'open({str(ran)!r}, "w").close()', 30)
		assert r['error_type'] == 'DomainFilterDown' and 'so it did not run this cell' in r['error'], r
		r = await repl.call('eval', f'open({str(ran)!r}, "w").close()', 30)  # finish_from_repl's expression
		assert r['error_type'] == 'DomainFilterDown', r
		assert not ran.exists()
		guard.ws_url = real
		assert await asyncio.to_thread(guard.connected.wait, 15)
		r = await repl.call('exec', f'open({str(ran)!r}, "w").close(); print("ran")', 30)
	finally:
		await repl.close()
		await browser.stop()
	assert r['error'] is None and ran.exists()
	assert r['output'].startswith(
		"[strict_domains: browser-use lost its connection to the browser's request filter (1x since the last cell); "
		'requests pages made until it reconnected were not filtered]\nran'
	), r['output']


async def test_agent_with_strict_domains_wires_the_filter(chrome, site, tmp_path):
	"""Agent(browser=Browser(..., strict_domains=True)): the prompt line, a blocked subresource's notice in the cell
	output, and the before-cell check."""
	Site.hits.clear()
	model, seen = script(
		('python', {'code': f'goto_url({site["allowed"] + "/probe?agent"!r}); wait_for_load(); wait(1); print("CELL")'}),
		('finish', {'success': True, 'result': 'done'}),
	)
	browser = Browser(cdp_url=chrome['http'], allowed_domains=['allowed.localhost'], strict_domains=True)
	checks, before_cell = [], browser.before_cell

	async def counted():
		checks.append(1)
		return await before_cell()

	browser.before_cell = counted  # type: ignore[method-assign]
	result = await Agent('Visit a page', model, browser=browser, workspace=tmp_path).run()
	assert result.status == 'completed', result.error
	first = next(m for m in seen[0] if isinstance(m, ModelRequest))
	assert 'The browser blocks every request to other hosts and to private or local addresses' in (first.instructions or '')
	returns = [
		p.content for m in result.messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart)
	]
	assert '[blocked: evil.localhost is not in allowed_domains (allowed.localhost). The browser did not load' in str(returns[0])
	assert checks == [1]
	assert evil_hits() == []


def test_strict_guard_fails_a_request_it_cannot_judge_and_keeps_its_connection(monkeypatch):
	"""An exception while judging a paused request used to escape the guard's read loop: the connection dropped and
	Chrome let every request through until the reconnect. Now that request fails and the guard reads on."""
	sent = []
	guard = Guard('ws://unused', DomainRules.of(['allowed.localhost'], strict=True))
	guard._ws = type('Ws', (), {'send': lambda self, raw: sent.append(json.loads(raw))})()

	def broken(self, url):
		raise ValueError('unreadable')

	monkeypatch.setattr(DomainRules, 'blocked', broken)
	guard._handle(
		{
			'method': 'Fetch.requestPaused',
			'params': {'requestId': 'r1', 'frameId': 'f', 'resourceType': 'XHR', 'request': {'url': 'http://x/'}},
		}
	)
	assert [(m['method'], m['params']) for m in sent] == [
		('Fetch.failRequest', {'requestId': 'r1', 'errorReason': 'BlockedByClient'})
	]
	assert guard.take() == (
		['[blocked: browser-use could not read this URL (ValueError). The browser did not load http://x/]'],
		1,
	)
