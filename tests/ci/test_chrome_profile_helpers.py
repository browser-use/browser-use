import json
from pathlib import Path

from browser_use.browser import chrome


def test_macos_profile_path_matches_detected_browser_variant(monkeypatch, tmp_path):
	monkeypatch.setattr(chrome.platform, 'system', lambda: 'Darwin')
	monkeypatch.setattr(Path, 'home', lambda: tmp_path)

	assert chrome.get_chrome_profile_path(
		None,
		executable_path='/Applications/Chromium.app/Contents/MacOS/Chromium',
	) == str(tmp_path / 'Library' / 'Application Support' / 'Chromium')
	assert chrome.get_chrome_profile_path(
		None,
		executable_path='/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
	) == str(tmp_path / 'Library' / 'Application Support' / 'Google' / 'Chrome Canary')
	assert chrome.get_chrome_profile_path(
		None,
		executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
	) == str(tmp_path / 'Library' / 'Application Support' / 'Google' / 'Chrome')


def test_list_chrome_profiles_uses_detected_browser_variant(monkeypatch, tmp_path):
	monkeypatch.setattr(chrome.platform, 'system', lambda: 'Darwin')
	monkeypatch.setattr(Path, 'home', lambda: tmp_path)
	monkeypatch.setattr(chrome, 'find_chrome_executable', lambda: '/Applications/Chromium.app/Contents/MacOS/Chromium')

	user_data_dir = tmp_path / 'Library' / 'Application Support' / 'Chromium'
	user_data_dir.mkdir(parents=True)
	(user_data_dir / 'Local State').write_text(
		json.dumps({'profile': {'info_cache': {'Profile 1': {'name': 'Work'}}}}),
		encoding='utf-8',
	)

	assert chrome.list_chrome_profiles() == [{'directory': 'Profile 1', 'name': 'Work'}]


def test_list_chrome_profiles_returns_empty_for_unexpected_json_shapes(monkeypatch, tmp_path):
	monkeypatch.setattr(chrome.platform, 'system', lambda: 'Darwin')
	monkeypatch.setattr(Path, 'home', lambda: tmp_path)
	monkeypatch.setattr(chrome, 'find_chrome_executable', lambda: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

	user_data_dir = tmp_path / 'Library' / 'Application Support' / 'Google' / 'Chrome'
	user_data_dir.mkdir(parents=True)

	for payload in (
		[],
		{'profile': {'info_cache': []}},
		{'profile': {'info_cache': {'Default': []}}},
	):
		(user_data_dir / 'Local State').write_text(json.dumps(payload), encoding='utf-8')
		assert chrome.list_chrome_profiles() == []
