import pathlib
import tempfile

import pytest

from browser_use.browser.profile import BrowserProfile


def test_extract_extension_cleans_up_temp_zip(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
	prof = BrowserProfile(user_data_dir=None, headless=True)
	crx = tmp_path / 'bad.crx'

	# valid CRX v3 header, payload that is not a zip -> BadZipFile inside the fallback branch
	crx.write_bytes(b'Cr24' + (3).to_bytes(4, 'little') + (0).to_bytes(4, 'little') + b'NOT_A_ZIP' * 100)

	custom_temp = tmp_path / 'temp'
	custom_temp.mkdir()
	monkeypatch.setenv('TMPDIR', str(custom_temp))
	monkeypatch.setattr(tempfile, 'tempdir', str(custom_temp))

	with pytest.raises(Exception):
		prof._extract_extension(crx, tmp_path / 'out')

	leaked = list(custom_temp.glob('*.zip'))
	assert not leaked, f'Temp zip file(s) leaked: {leaked}'
