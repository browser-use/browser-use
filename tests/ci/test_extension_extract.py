"""Tests for _extract_extension temp .zip file cleanup."""

import io
import os
import tempfile as _tempfile
import zipfile
from pathlib import Path

import pytest

from browser_use.browser.profile import BrowserProfile


def _make_crx(zip_data: bytes) -> bytes:
	"""Build a minimal CRX v3 file: 'Cr24' magic + empty header + zip data."""
	header = b'Cr24' + (3).to_bytes(4, 'little') + (0).to_bytes(4, 'little')
	return header + zip_data


def _valid_crx() -> bytes:
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, 'w') as zf:
		zf.writestr('manifest.json', '{"name": "test-ext", "version": "1.0.0"}')
	return _make_crx(buf.getvalue())


@pytest.fixture
def profile() -> BrowserProfile:
	return BrowserProfile(headless=True)


def _force_crx_header_path(monkeypatch, crx_path):
	"""Force _extract_extension down the CRX-header-skip branch.

	Modern zipfile can read most CRX files directly thanks to its
	prepended-data handling, which bypasses the temp-file extraction path
	entirely. Some layouts (CRX v2, unusual headers, older Pythons) cannot,
	so the header-skip branch is the one that must not leak temp files.
	This wrapper simulates that case deterministically.
	"""
	real_zipfile = zipfile.ZipFile

	def selective_zipfile(file, *args, **kwargs):
		if isinstance(file, (str, os.PathLike)) and Path(file) == crx_path:
			raise zipfile.BadZipFile('forced: direct CRX read not supported')
		return real_zipfile(file, *args, **kwargs)

	monkeypatch.setattr(zipfile, 'ZipFile', selective_zipfile)


class TestExtractExtensionTempZipCleanup:
	def test_successful_extraction_removes_temp_zip(self, tmp_path, monkeypatch, profile):
		"""A valid CRX extracts and leaves no temp .zip behind."""
		monkeypatch.setattr(_tempfile, 'tempdir', str(tmp_path))

		crx_path = tmp_path / 'ext.crx'
		crx_path.write_bytes(_valid_crx())
		extract_dir = tmp_path / 'extracted'
		_force_crx_header_path(monkeypatch, crx_path)

		profile._extract_extension(crx_path, extract_dir)

		assert (extract_dir / 'manifest.json').exists()
		assert list(tmp_path.glob('*.zip')) == []

	def test_failed_extraction_does_not_leak_temp_zip(self, tmp_path, monkeypatch, profile):
		"""A CRX whose embedded zip is corrupt raises and leaves no temp .zip."""
		monkeypatch.setattr(_tempfile, 'tempdir', str(tmp_path))

		crx_path = tmp_path / 'ext.crx'
		crx_path.write_bytes(_make_crx(b'this is not a zip archive'))
		extract_dir = tmp_path / 'extracted'

		with pytest.raises(Exception):
			profile._extract_extension(crx_path, extract_dir)

		assert list(tmp_path.glob('*.zip')) == []

	def test_temp_zip_unlinked_after_handle_closed(self, tmp_path, monkeypatch, profile):
		"""Temp file handle must be closed before unlink (Windows-safe ordering)."""
		monkeypatch.setattr(_tempfile, 'tempdir', str(tmp_path))
		real_ntf = _tempfile.NamedTemporaryFile
		opened = []

		def tracking_ntf(*args, **kwargs):
			f = real_ntf(*args, **kwargs)
			opened.append(f)
			return f

		monkeypatch.setattr(_tempfile, 'NamedTemporaryFile', tracking_ntf)
		real_unlink = os.unlink

		def guarded_unlink(path):
			# Unlinking a still-open file raises PermissionError on Windows;
			# assert the implementation never does that.
			assert all(f.closed for f in opened), (
				'os.unlink called while the temp zip handle is still open; '
				'on Windows this raises PermissionError'
			)
			return real_unlink(path)

		monkeypatch.setattr(os, 'unlink', guarded_unlink)

		crx_path = tmp_path / 'ext.crx'
		crx_path.write_bytes(_valid_crx())
		extract_dir = tmp_path / 'extracted'
		_force_crx_header_path(monkeypatch, crx_path)

		profile._extract_extension(crx_path, extract_dir)

		assert (extract_dir / 'manifest.json').exists()
		assert list(tmp_path.glob('*.zip')) == []
