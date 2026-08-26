import tomllib
from pathlib import Path

from browser_use.utils import _is_newer_browser_use_version, _strip_utf8_bom, get_browser_use_version


def test_get_browser_use_version_reads_project_version_from_pyproject_toml(monkeypatch):
	"""Ensure tomllib-based parsing returns the [project] version and sets LIBRARY_VERSION."""
	import os

	get_browser_use_version.cache_clear()
	monkeypatch.delenv('LIBRARY_VERSION', raising=False)
	version = get_browser_use_version()
	pyproject = Path(__file__).parent.parent.parent.parent / 'pyproject.toml'
	assert pyproject.exists()
	import tomllib

	with open(pyproject, 'rb') as f:
		expected = tomllib.load(f)['project']['version']
	assert version == expected
	assert version != 'unknown'
	assert os.environ.get('LIBRARY_VERSION') == expected


def test_get_browser_use_version_handles_utf8_bom_in_pyproject_toml(monkeypatch):
	"""A UTF-8 BOM (as Windows editors save) must not make version detection return 'unknown'."""

	get_browser_use_version.cache_clear()
	monkeypatch.delenv('LIBRARY_VERSION', raising=False)
	pyproject = Path(__file__).parent.parent.parent.parent / 'pyproject.toml'
	original = pyproject.read_bytes()
	expected = tomllib.loads(original.decode('utf-8'))['project']['version']
	try:
		pyproject.write_bytes(b'\xef\xbb\xbf' + original)
		version = get_browser_use_version()
	finally:
		pyproject.write_bytes(original)
		get_browser_use_version.cache_clear()
	assert version == expected
	assert version != 'unknown'


def test_get_browser_use_version_falls_back_when_pyproject_has_no_project_version(monkeypatch):
	"""A parseable pyproject.toml without [project].version must fall back to installed metadata."""
	from importlib.metadata import version as get_version

	get_browser_use_version.cache_clear()
	monkeypatch.delenv('LIBRARY_VERSION', raising=False)
	pyproject = Path(__file__).parent.parent.parent.parent / 'pyproject.toml'
	original = pyproject.read_bytes()
	expected = get_version('browser-use')
	try:
		pyproject.write_bytes(b'[tool.ruff]\ntarget-version = "py311"\n')
		version = get_browser_use_version()
	finally:
		pyproject.write_bytes(original)
		get_browser_use_version.cache_clear()
	assert version == expected
	assert version != 'unknown'


def test_prerelease_is_newer_than_previous_stable():
	assert _is_newer_browser_use_version('0.12.9', '0.13.0rc3') is False


def test_stable_release_is_newer_than_same_release_candidate():
	assert _is_newer_browser_use_version('0.13.0', '0.13.0rc3') is True


def test_later_release_candidate_is_newer():
	assert _is_newer_browser_use_version('0.13.0rc4', '0.13.0rc3') is True


def test_strip_utf8_bom_only_removes_a_full_bom_prefix():
	"""A full UTF-8 BOM (EF BB BF) is stripped; partial or lone BOM bytes are not."""
	assert _strip_utf8_bom(b'\xef\xbb\xbf[project]\nversion = "1.0"') == b'[project]\nversion = "1.0"'
	assert _strip_utf8_bom(b'\xef\xbb[project]') == b'\xef\xbb[project]'
	assert _strip_utf8_bom(b'\xbb\xbf[project]') == b'\xbb\xbf[project]'
	assert _strip_utf8_bom(b'\xef[project]') == b'\xef[project]'
	assert _strip_utf8_bom(b'\xbb[project]') == b'\xbb[project]'
	assert _strip_utf8_bom(b'\xbf[project]') == b'\xbf[project]'
	assert _strip_utf8_bom(b'\xef\xbb\xbf\xef\xbb\xbf') == b'\xef\xbb\xbf'
	assert _strip_utf8_bom(b'[project]\nversion = "1.0"') == b'[project]\nversion = "1.0"'
	assert _strip_utf8_bom(b'') == b''
