"""Agent on a cloud browser: a task on one-country sites gets an exit in that country unless the user chose one."""

import pytest

from browser_use import Agent
from browser_use.browser import Browser
from browser_use.browser.browser import PROXY_COUNTRIES, site_country


@pytest.mark.parametrize(
	'task, want',
	[
		("On lamoda.ru, search for 'Nike Air Force 1' and report the price", 'ru'),
		('Open https://www.cwjobs.co.uk/jobs and list 3 Python roles', 'gb'),  # .uk is GB
		('Go to megamarket.ru then avito.ru and compare', 'ru'),
		('Check spiegel.de and zeit.de headlines.', 'de'),
		('On amazon.com, search for a cable', None),  # generic TLD: no country
		('Compare prices on ozon.ru and amazon.com', None),  # mixed: keep the default
		('Check lemonde.fr and spiegel.de', None),  # two countries
		('Find the docs on example.io', None),  # .io, .ai, .co... are generic names
		('Email me at bob@example.de about it', None),  # an email address is not a site
		('Open baidu.cn', None),  # a country the cloud has no exits in
		('Find a flight, budget 1.5k, version 2.0', None),
	],
)
def test_site_country(task, want):
	assert site_country(task) == want


def test_every_country_it_picks_is_one_the_cloud_accepts():
	assert {'gb', 'de', 'ru', 'kr', 'jp', 'fr'} <= PROXY_COUNTRIES and 'uk' not in PROXY_COUNTRIES


@pytest.mark.asyncio
async def test_the_agent_matches_the_exit_country_only_when_the_user_left_it_at_the_default(monkeypatch, tmp_path):
	monkeypatch.setenv('BROWSER_USE_API_KEY', 'fake-test-key')
	seen = []

	class Stop(Exception):
		pass

	async def start(self):
		seen.append(self.proxy)
		raise Stop

	monkeypatch.setattr(Browser, 'start', start)
	for browser, task, want in (
		(Browser(), 'On lamoda.ru find sneakers', 'ru'),
		(Browser(), 'On amazon.com find a cable', 'us'),
		(Browser(cloud_proxy_country_code='us'), 'On lamoda.ru find sneakers', 'us'),  # the user's choice wins
		(Browser(cloud_proxy_country_code=None), 'On lamoda.ru find sneakers', None),  # no proxy stays no proxy
	):
		seen.clear()
		await Agent(task, 'test', browser=browser, workspace=tmp_path).run(max_steps=1)  # stops at start: no browser
		assert seen == [want], (task, seen)
