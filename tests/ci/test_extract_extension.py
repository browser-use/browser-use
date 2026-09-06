"""Tests for BrowserProfile._extract_extension corruption handling.

Regression coverage for issue #5506: a .crx whose zip payload has a corrupt
end-of-central-directory *offset* field makes ``zipfile`` raise
``OSError: [Errno 22] Invalid argument`` (real files) instead of
``BadZipFile``, which escaped the old ``except zipfile.BadZipFile`` guard and
skipped the CRX-header fallback entirely.
"""

import io
import struct
import tempfile
import zipfile

import pytest

from browser_use.browser.profile import BrowserProfile

CRX3_HEADER = b'crx3-header-placeholder'


def _make_crx(payload: bytes) -> bytes:
	return b'Cr24' + struct.pack('<I', 3) + struct.pack('<I', len(CRX3_HEADER)) + CRX3_HEADER + payload


def _zip_payload(corrupt_eocd_offset: bool) -> bytes:
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, 'w') as z:
		z.writestr('manifest.json', '{"manifest_version": 3}')
	payload = bytearray(buf.getvalue())
	if corrupt_eocd_offset:
		eocd = len(payload) - 22
		payload[eocd + 16 : eocd + 20] = struct.pack('<I', 0xDEADBEEF)
	return bytes(payload)


class TestExtractExtension:
	def test_extracts_intact_crx_via_header_fallback(self, tmp_path):
		"""A standard Cr24-wrapped zip extracts through the header fallback."""
		crx = tmp_path / 'ext.crx'
		crx.write_bytes(_make_crx(_zip_payload(corrupt_eocd_offset=False)))
		out = tmp_path / 'out'

		BrowserProfile()._extract_extension(crx, out)

		assert (out / 'manifest.json').exists()

	def test_corrupt_eocd_zip_without_crx_magic_reports_clear_error(self, tmp_path):
		"""Corrupt-EOCD zip without Cr24 magic raises the clear format error
		instead of a bare ``OSError: [Errno 22]`` (the issue #5506 improvement)."""
		crx = tmp_path / 'ext.crx'
		crx.write_bytes(_zip_payload(corrupt_eocd_offset=True))
		out = tmp_path / 'out'

		with pytest.raises(Exception, match='Invalid CRX file format'):
			BrowserProfile()._extract_extension(crx, out)

	def test_corrupt_eocd_crx_reaches_header_fallback(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
		"""Issue #5506 repro: the corrupt-EOCD OSError must be caught by the
		widened guard so the header fallback runs (and then reports its own
		failure for the corrupt payload) instead of escaping at first attempt."""
		calls = []
		real_named_temporary_file = tempfile.NamedTemporaryFile

		def spy(*args, **kwargs):
			calls.append(1)
			return real_named_temporary_file(*args, **kwargs)

		monkeypatch.setattr(tempfile, 'NamedTemporaryFile', spy)

		crx = tmp_path / 'corrupt_eocd.crx'
		crx.write_bytes(_make_crx(_zip_payload(corrupt_eocd_offset=True)))
		out = tmp_path / 'out'

		with pytest.raises(Exception):
			BrowserProfile()._extract_extension(crx, out)

		assert calls, 'CRX-header fallback was not reached'
