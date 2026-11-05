import io
import logging
import struct
import tempfile
import zipfile
from pathlib import Path

import pytest

from browser_use.browser.profile import BrowserProfile


@pytest.mark.parametrize('archive_format', ['zip', 'crx2', 'crx3'])
@pytest.mark.parametrize('corruption', ['negative_after_header', 'negative', 'at_eof', 'past_eof'])
def test_corrupt_crx_warning_identifies_cached_file(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, corruption: str, archive_format: str
) -> None:
	monkeypatch.setenv('BROWSER_USE_CONFIG_DIR', str(tmp_path))
	monkeypatch.setattr(logging.getLogger('browser_use'), 'propagate', True)
	monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
	cache_dir = tmp_path / 'extensions'
	cache_dir.mkdir()

	archive = io.BytesIO()
	with zipfile.ZipFile(archive, 'w') as zip_file:
		zip_file.writestr('manifest.json', '{"manifest_version": 3}')

	crx_header = {'zip': b'', 'crx2': b'Cr24' + struct.pack('<III', 2, 0, 0), 'crx3': b'Cr24' + struct.pack('<II', 3, 0)}[
		archive_format
	]
	payload = archive.getvalue()
	corrupt_payload = bytearray(payload)
	if corruption in ('at_eof', 'past_eof'):
		# A member's local-header offset is 42 bytes into its central-directory record.
		central_directory = corrupt_payload.index(b'PK\x01\x02')
		member_offset = len(payload) + (corruption == 'past_eof')
		struct.pack_into('<I', corrupt_payload, central_directory + 42, member_offset)
	else:
		# The central-directory offset is six bytes from the end of the comment-free archive.
		# A small increase gives a negative member offset only after the CRX header is stripped.
		(directory_offset,) = struct.unpack_from('<I', corrupt_payload, -6)
		offset_increase = 1 if corruption == 'negative_after_header' else 0xDEADBEEF
		struct.pack_into('<I', corrupt_payload, -6, directory_offset + offset_increase)
	crx_path = cache_dir / 'ddkjiahejlhfcafbddmgiahcphecmpfh.crx'
	crx_path.write_bytes(crx_header + corrupt_payload)

	valid_ids = ('edibdbjcniadpccecjdfdjjppcpchdlm', 'gidlfommnbibbmegmgajdbikelkdcmcl')
	for extension_id in valid_ids:
		(cache_dir / f'{extension_id}.crx').write_bytes(crx_header + payload)

	args = BrowserProfile(user_data_dir=tmp_path / 'profile', enable_default_extensions=True).get_args()

	assert f'--load-extension={",".join(str(cache_dir / extension_id) for extension_id in valid_ids)}' in args
	warning = next(message for message in caplog.messages if 'Failed to setup uBlock Origin Lite extension' in message)
	assert str(crx_path) in warning
	assert list(tmp_path.glob('*.zip')) == []
