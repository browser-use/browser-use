import inspect
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog


def test_clear_text_field_does_not_dispatch_premature_change_event():
	"""Verify _clear_text_field dispatches 'input' but not premature 'change' events."""
	source = inspect.getsource(DefaultActionWatchdog._clear_text_field)
	assert 'Event("change"' not in source
	assert "Event('change'" not in source
	assert 'Event("input"' in source
