"""Unit tests for SessionManager target/session bookkeeping.

These tests exercise the pure bookkeeping logic of SessionManager without
spinning up a real browser or CDP connection.
"""

import logging

import pytest

from browser_use.browser.session import Target
from browser_use.browser.session_manager import SessionManager


class _FakeBrowserSession:
	def __init__(self):
		self.logger = logging.getLogger('test_session_manager')


@pytest.fixture
def session_manager():
	sm = SessionManager(_FakeBrowserSession())
	sm._targets = {
		'page-a': Target(target_id='page-a', target_type='page', url='https://example.com/'),
		'page-b': Target(target_id='page-b', target_type='tab', url='https://example.org/'),
		'newtab': Target(target_id='newtab', target_type='page', url='about:blank'),
		'ext': Target(target_id='ext', target_type='page', url='chrome-extension://abc123/panel.html'),
		'ext-bg': Target(target_id='ext-bg', target_type='tab', url='chrome-extension://abc123/background.html'),
		'iframe': Target(target_id='iframe', target_type='iframe', url='https://example.com/embed'),
		'worker': Target(target_id='worker', target_type='worker', url='https://example.com/worker.js'),
	}
	return sm


def test_get_all_page_targets_excludes_chrome_extension(session_manager):
	"""Chrome extension targets must never be surfaced as agent-visible pages.

	Regression test for #4133: agent focus could switch to chrome-extension://
	targets because get_all_page_targets() only filtered on target type.
	"""
	targets = session_manager.get_all_page_targets()

	urls = [t.url for t in targets]
	assert 'chrome-extension://abc123/panel.html' not in urls
	assert 'chrome-extension://abc123/background.html' not in urls


def test_get_all_page_targets_keeps_real_pages(session_manager):
	"""Normal pages, tabs, and new-tab pages are still returned."""
	targets = session_manager.get_all_page_targets()

	urls = {t.url for t in targets}
	assert urls == {'https://example.com/', 'https://example.org/', 'about:blank'}


def test_get_all_page_targets_excludes_non_page_types(session_manager):
	"""Iframes and workers are still filtered out by target type."""
	targets = session_manager.get_all_page_targets()

	urls = {t.url for t in targets}
	assert 'https://example.com/embed' not in urls
	assert 'https://example.com/worker.js' not in urls
