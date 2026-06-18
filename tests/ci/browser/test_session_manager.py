import logging
from types import SimpleNamespace
from typing import cast

from browser_use.browser.session import BrowserSession, Target
from browser_use.browser.session_manager import SessionManager


def test_get_all_page_targets_excludes_chrome_extension_pages():
	browser_session = cast(
		BrowserSession,
		SimpleNamespace(
			logger=logging.getLogger('test_session_manager'),
			agent_focus_target_id=None,
		),
	)
	manager = SessionManager(browser_session)
	manager._targets = {
		'page-target': Target(
			target_id='page-target',
			target_type='page',
			url='https://example.com',
			title='Example',
		),
		'extension-side-panel': Target(
			target_id='extension-side-panel',
			target_type='page',
			url='chrome-extension://abc123/side-panel.html',
			title='Extension side panel',
		),
		'blank-tab': Target(
			target_id='blank-tab',
			target_type='tab',
			url='about:blank',
			title='New tab',
		),
		'worker-target': Target(
			target_id='worker-target',
			target_type='service_worker',
			url='https://example.com/sw.js',
			title='Worker',
		),
	}

	target_ids = [target.target_id for target in manager.get_all_page_targets()]

	assert target_ids == ['page-target', 'blank-tab']
