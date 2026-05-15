import logging

from browser_use.browser.session import Target
from browser_use.browser.session_manager import SessionManager


class FakeBrowserSession:
	logger = logging.getLogger(__name__)


def test_get_all_page_targets_excludes_chrome_extension_pages():
	session_manager = SessionManager(FakeBrowserSession())
	regular_page = Target(
		target_id='page-target',
		target_type='page',
		url='https://example.com',
		title='Example',
	)
	regular_tab = Target(
		target_id='tab-target',
		target_type='tab',
		url='https://docs.example.com',
		title='Docs',
	)
	extension_side_panel = Target(
		target_id='extension-side-panel',
		target_type='page',
		url='chrome-extension://abcdefghijklmnop/side-panel.html',
		title='Extension side panel',
	)
	iframe_target = Target(
		target_id='iframe-target',
		target_type='iframe',
		url='https://example.com/frame',
		title='Frame',
	)
	session_manager._targets = {
		regular_page.target_id: regular_page,
		extension_side_panel.target_id: extension_side_panel,
		regular_tab.target_id: regular_tab,
		iframe_target.target_id: iframe_target,
	}

	targets = session_manager.get_all_page_targets()

	assert targets == [regular_page, regular_tab]
