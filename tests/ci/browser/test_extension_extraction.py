import io
import os
import struct
import tempfile
import zipfile
from pathlib import Path

import pytest

from browser_use.browser.profile import BrowserProfile


HDR = b'crx3-header-placeholder'


def _make_crx(payload: bytes) -> bytes:
	return b'Cr24' + struct.pack('<I', 3) + struct.pack('<I', len(HDR)) + HDR + payload


def _make_valid_zip_payload() -> bytes:
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, 'w') as z:
		z.writestr('manifest.json', '{"manifest_version": 3}')
	return buf.getvalue()


def test_extract_valid_crx(tmp_path: Path) -> None:
	crx_path = tmp_path / 'extension.crx'
	crx_path.write_bytes(_make_crx(_make_valid_zip_payload()))
	extract_dir = tmp_path / 'extracted'

	BrowserProfile()._extract_extension(crx_path, extract_dir)
	assert (extract_dir / 'manifest.json').exists()


def test_extract_valid_zip_without_crx_header(tmp_path: Path) -> None:
	crx_path = tmp_path / 'extension.zip'
	crx_path.write_bytes(_make_valid_zip_payload())
	extract_dir = tmp_path / 'extracted'

	BrowserProfile()._extract_extension(crx_path, extract_dir)
	assert (extract_dir / 'manifest.json').exists()


def test_extract_corrupt_eocd_offset_raises_invalid_crx_error(tmp_path: Path) -> None:
	payload = bytearray(_make_valid_zip_payload())
	eocd = len(payload) - 22
	payload[eocd + 16 : eocd + 20] = struct.pack('<I', 0xDEADBEEF)

	crx_path = tmp_path / 'corrupt_eocd.crx'
	crx_path.write_bytes(_make_crx(bytes(payload)))
	extract_dir = tmp_path / 'extracted'

	with pytest.raises(Exception, match='Invalid CRX file format'):
		BrowserProfile()._extract_extension(crx_path, extract_dir)


def test_extract_invalid_magic_raises_invalid_crx_error(tmp_path: Path) -> None:
	crx_path = tmp_path / 'invalid_magic.crx'
	crx_path.write_bytes(b'XXXX' + struct.pack('<I', 3) + b'rest')
	extract_dir = tmp_path / 'extracted'

	with pytest.raises(Exception, match='Invalid CRX file format'):
		BrowserProfile()._extract_extension(crx_path, extract_dir)


def test_extract_missing_manifest_raises_error(tmp_path: Path) -> None:
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, 'w') as z:
		z.writestr('other.txt', 'no manifest')

	crx_path = tmp_path / 'no_manifest.crx'
	crx_path.write_bytes(_make_crx(buf.getvalue()))
	extract_dir = tmp_path / 'extracted'

	with pytest.raises(Exception, match='No manifest.json found in extension'):
		BrowserProfile()._extract_extension(crx_path, extract_dir)
