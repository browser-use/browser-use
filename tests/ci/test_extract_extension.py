"""Regression tests for BrowserProfile._extract_extension CRX fallback path.

See https://github.com/browser-use/browser-use/issues/5364 - when the raw CRX
can't be opened as a zip directly, the header-stripping fallback writes the
payload to a NamedTemporaryFile and must always clean it up, even when the
stripped payload itself isn't a valid zip (e.g. truncated download, unknown
CRX version, corrupted header offset).
"""

import glob
import os
import tempfile
from pathlib import Path

import pytest

from browser_use.browser.profile import BrowserProfile


def _make_headered_non_zip_crx(version: int = 3, header_len: int = 0) -> bytes:
	"""Build a CRX-shaped file whose payload is not a valid zip at all.

	This forces the direct `zipfile.ZipFile(crx_path)` open to raise
	BadZipFile (so the header-stripping fallback in `_extract_extension`
	is entered), AND makes the header-stripped payload also fail to open
	as a zip, which is the scenario that used to leak the temp file.
	"""
	payload = b'not a zip file at all, no end-of-central-directory signature here'
	if version == 2:
		pubkey_len = 0
		sig_len = 0
		header = (2).to_bytes(4, 'little') + pubkey_len.to_bytes(4, 'little') + sig_len.to_bytes(4, 'little')
	else:
		header = (3).to_bytes(4, 'little') + header_len.to_bytes(4, 'little') + (b'\x00' * header_len)
	return b'Cr24' + header + payload


class TestExtractExtensionCrxFallback:
	def test_no_temp_zip_leaked_when_fallback_payload_is_invalid(self, tmp_path: Path):
		"""When both the direct and header-stripped opens fail, no .zip temp file should remain."""
		profile = BrowserProfile(headless=True)

		crx_path = tmp_path / 'broken.crx'
		crx_path.write_bytes(_make_headered_non_zip_crx())
		extract_dir = tmp_path / 'extracted'

		tempdir = tempfile.gettempdir()
		before = set(glob.glob(os.path.join(tempdir, '*.zip')))

		with pytest.raises(Exception):
			profile._extract_extension(crx_path, extract_dir)

		after = set(glob.glob(os.path.join(tempdir, '*.zip')))
		leaked = after - before
		assert not leaked, f'_extract_extension leaked temp file(s) on failure: {leaked}'

	def test_raises_instead_of_permission_error_on_cleanup(self, tmp_path: Path):
		"""The failure raised should come from the zip extraction itself, not from cleanup."""
		profile = BrowserProfile(headless=True)

		crx_path = tmp_path / 'broken.crx'
		crx_path.write_bytes(_make_headered_non_zip_crx())
		extract_dir = tmp_path / 'extracted'

		import zipfile

		with pytest.raises(zipfile.BadZipFile):
			profile._extract_extension(crx_path, extract_dir)
