from pathlib import Path

import pytest

from browser_use.browser.profile import BrowserProfile


def test_default_download_paths_do_not_create_directories_until_browser_launch(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""Creating unused profiles reserves distinct paths without creating folders."""
	monkeypatch.setattr('browser_use.browser.profile.tempfile.gettempdir', lambda: str(tmp_path))
	profiles = [BrowserProfile() for _ in range(3)]
	paths = [Path(profile.downloads_path) for profile in profiles if profile.downloads_path is not None]
	assert len(set(paths)) == 3
	assert all(not path.exists() for path in paths)
	assert list(tmp_path.iterdir()) == []


def test_explicit_download_path_is_not_created_during_profile_construction(tmp_path: Path) -> None:
	"""User-specified download directories remain untouched until the browser uses them."""
	path = tmp_path / 'downloads'
	profile = BrowserProfile(downloads_path=path)
	assert profile.downloads_path is not None
	assert Path(profile.downloads_path) == path
	assert not path.exists()
