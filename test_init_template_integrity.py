import pytest

from browser_use import init_cmd


class _FakeResponse:
	def __init__(self, payload: bytes):
		self._payload = payload

	def read(self) -> bytes:
		return self._payload

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc, tb):
		return False


def test_get_template_list_uses_pinned_manifest():
	templates = init_cmd._get_template_list()
	assert 'default' in templates
	assert templates['default']['file'] == 'default_template.py'


def test_get_template_content_verifies_integrity(monkeypatch):
	expected = b'print("hello from trusted template")\n'
	monkeypatch.setitem(
		init_cmd.TRUSTED_INIT_TEMPLATE_HASHES,
		'default_template.py',
		'sha256:b01e1c9b58b5597a14225c83d0a56697ffee57151031ec6476eb1cb495fefc98',
	)

	def fake_urlopen(url: str, timeout: int = 5):
		assert url.endswith('/default_template.py')
		return _FakeResponse(expected)

	monkeypatch.setattr(init_cmd.request, 'urlopen', fake_urlopen)

	assert init_cmd._get_template_content('default_template.py') == expected.decode('utf-8')


def test_get_template_content_rejects_hash_mismatch(monkeypatch):
	monkeypatch.setitem(
		init_cmd.TRUSTED_INIT_TEMPLATE_HASHES,
		'default_template.py',
		'sha256:' + '0' * 64,
	)

	def fake_urlopen(url: str, timeout: int = 5):
		return _FakeResponse(b'print("tampered")\n')

	monkeypatch.setattr(init_cmd.request, 'urlopen', fake_urlopen)

	with pytest.raises(FileNotFoundError):
		init_cmd._get_template_content('default_template.py')


def test_fetch_binary_from_github_verifies_integrity(monkeypatch):
	expected = b'%PDF-1.4 fake content'
	monkeypatch.setitem(
		init_cmd.TRUSTED_INIT_TEMPLATE_HASHES,
		'job-application/example_resume.pdf',
		'sha256:3b43ec6ec0c8acdacd3d7fbf26014157f8b2290a7c9a84d518f9fbe410d96b72',
	)

	def fake_urlopen(url: str, timeout: int = 5):
		assert url.endswith('/job-application/example_resume.pdf')
		return _FakeResponse(expected)

	monkeypatch.setattr(init_cmd.request, 'urlopen', fake_urlopen)

	assert init_cmd._fetch_binary_from_github('job-application/example_resume.pdf') == expected
