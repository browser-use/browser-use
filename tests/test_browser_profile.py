from pathlib import Path

import pytest

from browser_use.browser.profile import BrowserProfile


@pytest.mark.parametrize(
	'executable_path',
	[
		'/test/chrome',  # str
		Path('/test/chrome'),  # Path
		None,  # None
	],
	ids=['str', 'Path', 'None'],
)
def test_executable_path_field_types(executable_path):
	"""Test executable_path accepts str, Path, and None types without throwing exceptions."""
	BrowserProfile(executable_path=executable_path)


@pytest.mark.parametrize(
	'user_data_dir',
	[
		'/test/profile',  # str
		Path('/test/profile'),  # Path
		None,  # None - incognito mode
	],
	ids=['str', 'Path', 'None'],
)
def test_user_data_dir_field_types(user_data_dir):
	"""Test user_data_dir accepts str, Path, and None types without throwing exceptions."""
	BrowserProfile(user_data_dir=user_data_dir)
