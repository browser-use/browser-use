"""Tests for BrowserProfile._extract_extension() temp-file handling.

`_extract_extension()` has two branches:

1. Open the .crx directly with `ZipFile(crx_path)`. Python's zipfile scans
   backwards for the end-of-central-directory record and corrects the
   central-directory offsets for any prepended bytes (the same support that
   makes self-extracting archives work), so an **intact** .crx opens here
   despite its `Cr24` header. No temp file is involved.
2. On BadZipFile, skip the CRX header, write the remaining payload to a
   `delete=False` temp .zip, and extract that. This branch owns the temp
   file's lifetime completely.

Because the only difference between the two inputs is the leading header, and
zipfile self-corrects for it, branch 2 is reached exactly when the zip payload
is damaged enough that branch 1 could not read it — in which case branch 2
cannot read it either. So the realistic behaviour of branch 2 is: enter, fail,
and (before this fix) strand a .zip in the system temp dir.

The tests below therefore pin *which* branch they exercise rather than assuming.
"""

import struct
import tempfile
import traceback
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from browser_use.browser.profile import BrowserProfile

CRX_HEADER = b'crx3-header-placeholder'


def _make_crx(payload: bytes, crx_header: bytes = CRX_HEADER) -> bytes:
	"""Build a CRX v3 container: magic + version + header length + header + payload."""
	return b'Cr24' + struct.pack('<I', 3) + struct.pack('<I', len(crx_header)) + crx_header + payload


def _make_zip_payload() -> bytes:
	"""A minimal but genuine zip archive holding an extension manifest."""
	buffer = BytesIO()
	with zipfile.ZipFile(buffer, 'w') as archive:
		archive.writestr('manifest.json', '{"name": "test", "version": "1.0", "manifest_version": 3}')
	return buffer.getvalue()


@pytest.fixture
def temp_dir(tmp_path, monkeypatch) -> Path:
	"""Point tempfile at a private directory so leaked temp files are attributable."""
	temp_root = tmp_path / 'tmp'
	temp_root.mkdir()
	monkeypatch.setattr(tempfile, 'tempdir', str(temp_root))
	return temp_root


def _leaked_zips(temp_dir: Path) -> list[Path]:
	return list(temp_dir.glob('*.zip'))


class TestExtractExtensionTempFileCleanup:
	def test_no_temp_zip_left_behind_when_header_skip_extraction_fails(self, tmp_path, temp_dir):
		"""Branch 2: a CRX whose payload is not a valid zip must not leak its temp .zip."""
		crx_path = tmp_path / 'corrupt.crx'
		crx_path.write_bytes(_make_crx(b'this is not a zip archive'))

		profile = BrowserProfile()

		with pytest.raises(zipfile.BadZipFile) as exc_info:
			profile._extract_extension(crx_path, tmp_path / 'extracted')

		# Pin the branch: the failure must come from the temp-file extraction in the
		# header-skipping fallback, not from the initial in-place ZipFile attempt.
		# Without this the leak assertion below could pass vacuously.
		frames = traceback.extract_tb(exc_info.tb)
		assert any(frame.line and 'ZipFile(temp_zip' in frame.line for frame in frames), (
			f'expected the header-skipping branch to raise, got frames: {[f.line for f in frames]}'
		)

		assert _leaked_zips(temp_dir) == [], 'temp .zip survived a failed extraction'

	def test_intact_crx_extracts_in_place_without_creating_a_temp_zip(self, tmp_path, temp_dir):
		"""Branch 1: an intact CRX opens directly, so no temp file is ever created.

		This does not exercise the fallback cleanup — it documents that the common
		case never reaches it, and guards the method's overall no-leak invariant.
		"""
		crx_path = tmp_path / 'valid.crx'
		crx_path.write_bytes(_make_crx(_make_zip_payload()))
		extract_dir = tmp_path / 'extracted'

		# Precondition for the branch this test claims to cover.
		with zipfile.ZipFile(crx_path, 'r') as archive:
			assert archive.namelist() == ['manifest.json']

		profile = BrowserProfile()
		profile._extract_extension(crx_path, extract_dir)

		assert (extract_dir / 'manifest.json').exists()
		assert _leaked_zips(temp_dir) == []


class TestExtractExtensionCleanupErrors:
	def test_cleanup_failure_does_not_mask_the_extraction_error(self, tmp_path, temp_dir, monkeypatch):
		"""A failing unlink in the `finally` must not replace the real exception."""
		crx_path = tmp_path / 'corrupt.crx'
		crx_path.write_bytes(_make_crx(b'this is not a zip archive'))

		original_unlink = Path.unlink

		def failing_unlink(self, *args, **kwargs):
			if self.suffix == '.zip':
				raise PermissionError(32, 'The process cannot access the file')
			return original_unlink(self, *args, **kwargs)

		monkeypatch.setattr(Path, 'unlink', failing_unlink)

		profile = BrowserProfile()

		# The caller must still see BadZipFile, not the PermissionError from cleanup.
		with pytest.raises(zipfile.BadZipFile):
			profile._extract_extension(crx_path, tmp_path / 'extracted')
