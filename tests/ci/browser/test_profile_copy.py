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


def test_user_data_dir_default_validation_when_omitted() -> None:
	"""user_data_dir field_validator should execute when field is omitted or explicitly None."""
	profile_explicit_none = BrowserProfile(user_data_dir=None)
	profile_omitted = BrowserProfile(headless=True)
	profile_empty = BrowserProfile()

	dir_explicit_none = profile_explicit_none.user_data_dir
	dir_omitted = profile_omitted.user_data_dir
	dir_empty = profile_empty.user_data_dir

	try:
		assert dir_explicit_none is not None
		assert dir_omitted is not None
		assert dir_empty is not None

		assert 'browser-use-user-data-dir-' in str(dir_explicit_none)
		assert 'browser-use-user-data-dir-' in str(dir_omitted)
		assert 'browser-use-user-data-dir-' in str(dir_empty)
	finally:
		if dir_explicit_none is not None:
			shutil.rmtree(dir_explicit_none, ignore_errors=True)
		if dir_omitted is not None:
			shutil.rmtree(dir_omitted, ignore_errors=True)
		if dir_empty is not None:
			shutil.rmtree(dir_empty, ignore_errors=True)
