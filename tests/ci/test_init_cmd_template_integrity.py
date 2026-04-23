import hashlib
import json
from typing import Callable

import pytest

from browser_use import init_cmd


class _FakeResponse:
	def __init__(self, payload: bytes):
		self._payload = payload

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc, tb):
		return False

	def read(self) -> bytes:
		return self._payload


def _fake_urlopen_factory(payload_by_path: dict[str, bytes]) -> Callable:
	def _fake_urlopen(url: str, timeout: int = 5):
		prefix = f'{init_cmd.TEMPLATE_REPO_URL}/'
		assert url.startswith(prefix)
		path = url.removeprefix(prefix)
		if path not in payload_by_path:
			raise AssertionError(f'Unexpected URL path requested: {path}')
		return _FakeResponse(payload_by_path[path])

	return _fake_urlopen


def _sha256(data: bytes) -> str:
	return hashlib.sha256(data).hexdigest()


def test_fetch_template_list_returns_data_when_hash_matches(monkeypatch: pytest.MonkeyPatch):
	templates = {'default': {'description': 'Default template', 'file': 'default_template.py'}}
	templates_bytes = json.dumps(templates).encode('utf-8')

	monkeypatch.setattr(init_cmd, 'TEMPLATE_REPO_URL', 'https://example.test/template-library/pinned-commit')
	monkeypatch.setattr(init_cmd, 'TEMPLATE_FILE_HASHES', {'templates.json': _sha256(templates_bytes)})
	monkeypatch.setattr(
		init_cmd.request,
		'urlopen',
		_fake_urlopen_factory({'templates.json': templates_bytes}),
	)

	assert init_cmd._fetch_template_list() == templates


def test_fetch_template_list_returns_none_when_hash_mismatch(monkeypatch: pytest.MonkeyPatch):
	templates_bytes = b'{"default":{"description":"Default template","file":"default_template.py"}}'

	monkeypatch.setattr(init_cmd, 'TEMPLATE_REPO_URL', 'https://example.test/template-library/pinned-commit')
	monkeypatch.setattr(init_cmd, 'TEMPLATE_FILE_HASHES', {'templates.json': 'invalidhash'})
	monkeypatch.setattr(
		init_cmd.request,
		'urlopen',
		_fake_urlopen_factory({'templates.json': templates_bytes}),
	)

	assert init_cmd._fetch_template_list() is None


def test_fetch_from_github_returns_none_for_untrusted_file(monkeypatch: pytest.MonkeyPatch):
	file_path = 'default_template.py'
	file_bytes = b'print("hello")\n'

	monkeypatch.setattr(init_cmd, 'TEMPLATE_REPO_URL', 'https://example.test/template-library/pinned-commit')
	monkeypatch.setattr(init_cmd, 'TEMPLATE_FILE_HASHES', {file_path: 'invalidhash'})
	monkeypatch.setattr(
		init_cmd.request,
		'urlopen',
		_fake_urlopen_factory({file_path: file_bytes}),
	)

	assert init_cmd._fetch_from_github(file_path) is None
