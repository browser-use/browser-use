import shutil
from pathlib import Path

import pytest

from browser_use.browser import profile as profile_module
from browser_use.browser.profile import BrowserChannel, BrowserProfile


def _create_chrome_user_data_dir(tmp_path: Path) -> Path:
	user_data_dir = tmp_path / 'Chrome User Data'
	default_profile = user_data_dir / 'Default'
	default_profile.mkdir(parents=True)
	(default_profile / 'Preferences').write_text('{"profile": "default"}')
	(user_data_dir / 'Local State').write_text('{"browser": "chrome"}')
	return user_data_dir


def test_chrome_profile_copy_skips_transient_lock_files(tmp_path: Path) -> None:
	user_data_dir = _create_chrome_user_data_dir(tmp_path)
	default_profile = user_data_dir / 'Default'
	(default_profile / 'SingletonLock').write_text('locked')
	(default_profile / 'Cookies-journal').write_text('journal')

	browser_profile = BrowserProfile(
		user_data_dir=user_data_dir,
		channel=BrowserChannel.CHROME,
		headless=True,
	)

	assert browser_profile.user_data_dir is not None
	temp_user_data_dir = Path(browser_profile.user_data_dir)
	try:
		assert (temp_user_data_dir / 'Default' / 'Preferences').read_text() == '{"profile": "default"}'
		assert (temp_user_data_dir / 'Local State').read_text() == '{"browser": "chrome"}'
		assert not (temp_user_data_dir / 'Default' / 'SingletonLock').exists()
		assert not (temp_user_data_dir / 'Default' / 'Cookies-journal').exists()
	finally:
		shutil.rmtree(temp_user_data_dir, ignore_errors=True)


def test_chrome_profile_copy_lock_error_is_actionable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	user_data_dir = _create_chrome_user_data_dir(tmp_path)
	temp_user_data_dir = tmp_path / 'browser-use-user-data-dir-test'

	def fake_mkdtemp(prefix: str) -> str:
		temp_user_data_dir.mkdir()
		return str(temp_user_data_dir)

	def fake_copytree(*_args: object, **_kwargs: object) -> None:
		raise PermissionError(13, 'The process cannot access the file because it is being used by another process')

	monkeypatch.setattr(profile_module.tempfile, 'mkdtemp', fake_mkdtemp)
	monkeypatch.setattr(shutil, 'copytree', fake_copytree)

	with pytest.raises(RuntimeError, match='Close any Chrome windows using this profile.*--cdp-url'):
		BrowserProfile(
			user_data_dir=user_data_dir,
			channel=BrowserChannel.CHROME,
			headless=True,
		)

	assert not temp_user_data_dir.exists()
