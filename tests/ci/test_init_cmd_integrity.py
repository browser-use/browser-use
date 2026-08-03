import hashlib

import pytest

from browser_use import init_cmd


class FakeResponse:
	def __init__(self, content: bytes):
		self.content = content

	def __enter__(self):
		return self

	def __exit__(self, *_args):
		return None

	def read(self):
		return self.content


def fake_urlopen(content: bytes):
	def _urlopen(_url: str, timeout: int):
		assert timeout == 5
		return FakeResponse(content)

	return _urlopen


def test_template_manifest_hash_mismatch_is_blocked(monkeypatch):
	manifest = b'{"default": {"file": "default_template.py", "description": "tampered"}}'
	monkeypatch.setattr(init_cmd.request, 'urlopen', fake_urlopen(manifest))

	with pytest.raises(init_cmd.TemplateIntegrityError, match='Template integrity check failed'):
		init_cmd._fetch_template_list()


def test_template_manifest_rejects_unpinned_file_reference(monkeypatch):
	manifest = b'{"default": {"file": "evil.py", "description": "tampered"}}'
	monkeypatch.setitem(init_cmd.TEMPLATE_FILE_SHA256, init_cmd.TEMPLATE_MANIFEST_PATH, hashlib.sha256(manifest).hexdigest())
	monkeypatch.setattr(init_cmd.request, 'urlopen', fake_urlopen(manifest))

	with pytest.raises(init_cmd.TemplateIntegrityError, match='references an unpinned file'):
		init_cmd._fetch_template_list()


def test_template_file_hash_mismatch_is_blocked(monkeypatch):
	monkeypatch.setitem(init_cmd.TEMPLATE_FILE_SHA256, 'default_template.py', '0' * 64)
	monkeypatch.setattr(init_cmd.request, 'urlopen', fake_urlopen(b'print("tampered")'))

	with pytest.raises(init_cmd.TemplateIntegrityError, match='Template integrity check failed'):
		init_cmd._fetch_from_github('default_template.py')


def test_verified_template_file_is_returned(monkeypatch):
	content = b'print("hello")'
	monkeypatch.setitem(init_cmd.TEMPLATE_FILE_SHA256, 'default_template.py', hashlib.sha256(content).hexdigest())
	monkeypatch.setattr(init_cmd.request, 'urlopen', fake_urlopen(content))

	assert init_cmd._fetch_from_github('default_template.py') == 'print("hello")'


def test_verified_binary_template_file_is_returned(monkeypatch):
	content = b'%PDF-1.4 fake resume'
	monkeypatch.setitem(init_cmd.TEMPLATE_FILE_SHA256, 'job-application/example_resume.pdf', hashlib.sha256(content).hexdigest())
	monkeypatch.setattr(init_cmd.request, 'urlopen', fake_urlopen(content))

	assert init_cmd._fetch_binary_from_github('job-application/example_resume.pdf') == content
