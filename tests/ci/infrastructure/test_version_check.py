from pathlib import Path

from browser_use.utils import _is_newer_browser_use_version, get_browser_use_version


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


def test_prerelease_is_newer_than_previous_stable():
	assert _is_newer_browser_use_version('0.12.9', '0.13.0rc3') is False


def test_stable_release_is_newer_than_same_release_candidate():
	assert _is_newer_browser_use_version('0.13.0', '0.13.0rc3') is True


def test_later_release_candidate_is_newer():
	assert _is_newer_browser_use_version('0.13.0rc4', '0.13.0rc3') is True
