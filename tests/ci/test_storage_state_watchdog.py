from browser_use.browser.watchdogs.storage_state_watchdog import StorageStateWatchdog


def test_merge_storage_states_does_not_restore_deleted_cookies() -> None:
	existing = {
		'cookies': [
			{'name': 'session', 'value': 'old-token', 'domain': 'example.com', 'path': '/'},
			{'name': 'theme', 'value': 'light', 'domain': 'example.com', 'path': '/'},
		],
		'origins': [{'origin': 'https://previous.example', 'localStorage': [{'name': 'key', 'value': 'value'}]}],
	}
	current = {
		'cookies': [{'name': 'theme', 'value': 'dark', 'domain': 'example.com', 'path': '/'}],
		'origins': [],
	}

	merged = StorageStateWatchdog._merge_storage_states(existing, current)

	assert merged['cookies'] == current['cookies']
	assert merged['origins'] == existing['origins']
