import glob
import os
import pathlib
import tempfile

import pytest

from browser_use.browser.profile import BrowserProfile


def test_extract_extension_cleans_up_temp_zip():
	prof = BrowserProfile(user_data_dir=None, headless=True)
	tmpd = pathlib.Path(tempfile.mkdtemp())
	crx = tmpd / 'bad.crx'

	# valid CRX v3 header, payload that is not a zip -> BadZipFile inside the fallback branch
	crx.write_bytes(b'Cr24' + (3).to_bytes(4, 'little') + (0).to_bytes(4, 'little') + b'NOT_A_ZIP' * 100)

	pattern = os.path.join(tempfile.gettempdir(), 'tmp*.zip')
	before = set(glob.glob(pattern))

	with pytest.raises(Exception):
		prof._extract_extension(crx, tmpd / 'out')

	after = set(glob.glob(pattern))
	leaked = after - before

	assert not leaked, f'Temp zip file(s) leaked: {leaked}'
