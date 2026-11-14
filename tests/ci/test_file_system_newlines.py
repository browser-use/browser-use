import tempfile
from pathlib import Path
import pytest
from browser_use.filesystem.file_system import FileSystem

@pytest.mark.asyncio
async def test_base_file_newline_preservation_on_windows():
    with tempfile.TemporaryDirectory() as directory:
        fs = FileSystem(Path(directory), create_default_files=False)
        content = 'café\r\nfirst\nsecond'
        await fs.write_file('notes.txt', content)
        actual = (fs.data_dir / 'notes.txt').read_bytes()
        assert actual == content.encode('utf-8')