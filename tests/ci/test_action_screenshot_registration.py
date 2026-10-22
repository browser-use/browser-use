"""Tests for FileSystem registration of saved screenshots.

`screenshot(file_name=...)` used to write the PNG bytes directly into the
FileSystem's directory — the registry never gained an entry, so the agent
could not read_file / list_files / describe / display / upload the screenshot
it had just saved, and a FileSystem re-init (which clears data_dir) wiped it.
The write now goes through the same registration pipeline as write_file
(PNG magic validation + registry + disk sync) and reuses save_as_pdf's
"(N)" duplicate-name policy.
"""

import asyncio
import base64
import tempfile

from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.service import Tools

PNG_1PX = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='


class FakeSession:
	"""Only take_screenshot is exercised by the screenshot action."""

	def __init__(self):
		self.logger = None
		self.id = 'fake'
		self.cdp_client = None
		self.agent_focus_target_id = None
		self.session_manager = None

	async def take_screenshot(self, full_page=False):
		return base64.b64decode(PNG_1PX)


def _setup():
	tmp = tempfile.mkdtemp()
	fs = FileSystem(base_dir=tmp, create_default_files=True)
	return fs, FakeSession()


def _run(fs, session, **params):
	return asyncio.run(
		Tools().registry.execute_action(
			action_name='screenshot',
			params=params,
			browser_session=session,
			file_system=fs,
		)
	)


def test_saved_screenshot_is_registered_and_readable():
	fs, session = _setup()

	result = _run(fs, session, file_name='receipt')

	assert result.error is None
	assert 'receipt.png' in fs.files, 'the screenshot must appear in the FileSystem registry'
	disk = fs.get_dir() / 'receipt.png'
	assert disk.exists() and disk.read_bytes() == base64.b64decode(PNG_1PX)

	read = asyncio.run(fs.read_file('receipt.png'))
	assert 'not found' not in read.lower(), f'read_file must resolve the screenshot: {read!r}'


def test_saved_screenshot_visible_to_list_files_and_describe():
	fs, session = _setup()

	_run(fs, session, file_name='receipt')

	listed = fs.list_files()
	assert 'receipt.png' in listed, f'list_files must show the screenshot: {listed!r}'
	describe = fs.describe()
	assert 'receipt' in describe, f'describe() must show the screenshot: {describe[:200]!r}'


def test_duplicate_screenshot_names_get_counter_suffix():
	fs, session = _setup()

	first = _run(fs, session, file_name='receipt')
	second = _run(fs, session, file_name='receipt')

	assert 'Screenshot saved to receipt.png' in first.extracted_content
	assert 'Screenshot saved to receipt (1).png' in second.extracted_content
	assert 'receipt.png' in fs.files and 'receipt (1).png' in fs.files
	# The first screenshot must survive the second save
	assert (fs.get_dir() / 'receipt.png').read_bytes() == base64.b64decode(PNG_1PX)


def test_screenshot_without_file_name_only_flags_observation():
	fs, session = _setup()

	result = _run(fs, session)

	assert result.error is None
	assert result.metadata == {'include_screenshot': True}
	assert not any(name.endswith('.png') for name in fs.files), 'no file should be registered'
