"""Storage-state loading in the beta service.

``browser_use.browser.session`` writes storage state with ``ensure_ascii=False`` and
UTF-8, so the loader has to decode UTF-8 and treat an undecodable file as absent
instead of raising.
"""

import json

from browser_use.beta.service import _storage_state_value


def test_non_utf8_storage_state_is_treated_as_absent(tmp_path):
	path = tmp_path / 'state.json'
	path.write_bytes(b'\xff\xfe\x00')

	assert _storage_state_value(str(path)) is None


def test_utf8_storage_state_keeps_non_ascii_values(tmp_path):
	path = tmp_path / 'state.json'
	payload = {
		'cookies': [],
		'origins': [
			{
				'origin': 'https://agent.local',
				'localStorage': [{'name': 'k', 'value': '配置'}],
			}
		],
	}
	path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

	loaded = _storage_state_value(str(path))

	assert loaded is not None
	assert loaded['origins'][0]['localStorage'][0]['value'] == '配置'
