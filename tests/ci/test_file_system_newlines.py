from pathlib import Path
from unittest.mock import patch

import pytest

from browser_use.filesystem.file_system import FileSystem, TxtFile


@pytest.mark.asyncio
async def test_base_file_newline_preservation_async(tmp_path):
	with patch.object(Path, 'write_text') as mock_write_text:
		fs = FileSystem(tmp_path, create_default_files=False)
		content = 'café\r\nfirst\nsecond'

		# Test asynchronous write path (sync_to_disk)
		await fs.write_file('notes.txt', content)

		# Verify newline='' is explicitly passed to prevent Windows corruption
		mock_write_text.assert_called_with(content, encoding='utf-8', newline='')


def test_base_file_newline_preservation_sync(tmp_path):
	with patch.object(Path, 'write_text') as mock_write_text:
		content = 'café\r\nfirst\nsecond'
		txt_file = TxtFile(name='notes.txt', content=content)

		# Test synchronous write path directly using TxtFile (sync_to_disk_sync)
		txt_file.sync_to_disk_sync(tmp_path)

		# Verify newline='' is explicitly passed in the sync method as well
		mock_write_text.assert_called_with(content, encoding='utf-8', newline='')
