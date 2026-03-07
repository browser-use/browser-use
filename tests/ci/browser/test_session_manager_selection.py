from collections import deque
from unittest.mock import MagicMock

from browser_use.browser.session import BrowserSession, CDPSession, Target
from browser_use.browser.session_manager import SessionManager


def _make_session(target_id: str, session_id: str, attached_at: float, event_timestamps: list[float]) -> CDPSession:
	session = CDPSession.model_construct(cdp_client=MagicMock(), target_id=target_id, session_id=session_id)
	session._attached_at = attached_at
	session._lifecycle_events = deque(
		[
			{
				'name': 'load',
				'loaderId': f'loader-{session_id}',
				'timestamp': timestamp,
			}
			for timestamp in event_timestamps
		],
		maxlen=50,
	)
	return session


def test_get_session_for_target_prefers_freshest_lifecycle_session():
	browser_session = BrowserSession(headless=True)
	manager = SessionManager(browser_session)
	target_id = 'page-target-1'

	manager._targets[target_id] = Target(target_id=target_id, target_type='page')
	stale_session = _make_session(target_id, 'session-stale', attached_at=1.0, event_timestamps=[10.0])
	fresh_session = _make_session(target_id, 'session-fresh', attached_at=2.0, event_timestamps=[20.0, 21.0])
	manager._sessions[stale_session.session_id] = stale_session
	manager._sessions[fresh_session.session_id] = fresh_session
	manager._target_sessions[target_id] = {stale_session.session_id, fresh_session.session_id}

	assert manager._get_session_for_target(target_id) is fresh_session


def test_get_session_for_target_falls_back_to_latest_attachment_without_events():
	browser_session = BrowserSession(headless=True)
	manager = SessionManager(browser_session)
	target_id = 'page-target-2'

	manager._targets[target_id] = Target(target_id=target_id, target_type='page')
	older_session = _make_session(target_id, 'session-older', attached_at=1.0, event_timestamps=[])
	newer_session = _make_session(target_id, 'session-newer', attached_at=2.0, event_timestamps=[])
	manager._sessions[older_session.session_id] = older_session
	manager._sessions[newer_session.session_id] = newer_session
	manager._target_sessions[target_id] = {older_session.session_id, newer_session.session_id}

	assert manager._get_session_for_target(target_id) is newer_session


def test_get_session_for_target_prefers_newer_attachment_over_stale_old_events():
	browser_session = BrowserSession(headless=True)
	manager = SessionManager(browser_session)
	target_id = 'page-target-3'

	manager._targets[target_id] = Target(target_id=target_id, target_type='page')
	older_session = _make_session(target_id, 'session-older', attached_at=1.0, event_timestamps=[50.0])
	newer_session = _make_session(target_id, 'session-newer', attached_at=2.0, event_timestamps=[])
	manager._sessions[older_session.session_id] = older_session
	manager._sessions[newer_session.session_id] = newer_session
	manager._target_sessions[target_id] = {older_session.session_id, newer_session.session_id}

	assert manager._get_session_for_target(target_id) is newer_session
