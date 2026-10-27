"""Tests for FileSystem registration of pages saved as PDF.

`save_as_pdf` used to write the PDF bytes directly into the FileSystem's
directory — the registry never gained an entry, so the agent could not
read_file / list_files / describe / upload the page it had just saved, and a
FileSystem re-init (which clears data_dir) wiped it. The write now goes
through a RawPdfFile (validates the %PDF magic + registry + disk sync), and
duplicate names are checked against both the registry and disk.
"""

import asyncio
import base64
import tempfile
from types import SimpleNamespace

from browser_use.filesystem.file_system import FileSystem, RawPdfFile
from browser_use.tools.service import Tools

PDF_BYTES = b'%PDF-1.4 fake page content for testing'


class FakePageNamespace:
	def __init__(self, cdp):
		self._cdp = cdp

	def printToPDF(self, params, session_id=None):
		return self._cdp.print_result(params)


class FakeSendNamespace:
	def __init__(self, cdp):
		self.Page = FakePageNamespace(cdp)


class FakeCdp:
	def __init__(self):
		self.sent = []
		self.send = FakeSendNamespace(self)

	async def print_result(self, params):
		self.sent.append(params)
		return {'data': base64.b64encode(PDF_BYTES).decode()}


class FakeSession:
	def __init__(self):
		self.logger = None
		self.cdp_client = FakeCdp()
		self.session_id = 'fake'

	async def get_or_create_cdp_session(self, focus=False):
		return SimpleNamespace(cdp_client=self.cdp_client, session_id='fake')

	async def get_current_page_title(self):
		return 'Test Page'


def _run(fs, session, **params):
	return asyncio.run(
		Tools().registry.execute_action(
			action_name='save_as_pdf',
			params=params,
			browser_session=session,
			file_system=fs,
		)
	)


def _setup():
	tmp = tempfile.mkdtemp()
	fs = FileSystem(base_dir=tmp, create_default_files=True)
	return fs, FakeSession()


def test_saved_pdf_is_registered_and_readable():
	fs, session = _setup()

	result = _run(fs, session, file_name='report')

	assert result.error is None, f'save_as_pdf failed: {result.error!r}'
	assert 'report.pdf' in fs.files, 'the saved page must appear in the FileSystem registry'
	assert isinstance(fs.files['report.pdf'], RawPdfFile)
	disk = fs.get_dir() / 'report.pdf'
	assert disk.exists() and disk.read_bytes() == PDF_BYTES

	read = asyncio.run(fs.read_file('report.pdf'))
	assert 'not found' not in read.lower(), f'read_file must resolve the saved page: {read!r}'


def test_saved_pdf_visible_to_list_files():
	fs, session = _setup()

	_run(fs, session, file_name='report')

	assert 'report.pdf' in fs.list_files()


def test_duplicate_pdf_names_get_counter_suffix():
	fs, session = _setup()

	first = _run(fs, session, file_name='report')
	second = _run(fs, session, file_name='report')

	assert 'report.pdf' in first.extracted_content
	assert 'report (1).pdf' in second.extracted_content
	assert 'report.pdf' in fs.files and 'report (1).pdf' in fs.files
	# The first page must survive the second save
	assert (fs.get_dir() / 'report.pdf').read_bytes() == PDF_BYTES
