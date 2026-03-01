import asyncio
import tempfile

import anyio
import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.service import Tools


@pytest.fixture(scope='session')
def http_server():
	server = HTTPServer()
	server.start()

	server.expect_request('/pdf-test').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head><title>PDF Test Page</title></head>
		<body>
			<h1>Hello PDF</h1>
			<p>This page should be saved as a PDF document.</p>
			<ul>
				<li>Item 1</li>
				<li>Item 2</li>
				<li>Item 3</li>
			</ul>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	server.expect_request('/pdf-styled').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Styled PDF Page</title>
			<style>
				body { background-color: #f0f0f0; font-family: sans-serif; }
				h1 { color: navy; }
				.highlight { background-color: yellow; padding: 10px; }
			</style>
		</head>
		<body>
			<h1>Styled Content</h1>
			<div class="highlight">This has a background color that should appear when print_background=True.</div>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await browser_session.start()
	yield browser_session
	await browser_session.kill()


@pytest.fixture(scope='function')
def tools():
	return Tools()


def _get_attachments(result: ActionResult) -> list[str]:
	"""Helper to extract attachments with pyright-safe narrowing."""
	assert result.attachments is not None
	return result.attachments


class TestSaveAsPdf:
	"""Tests for the save_as_pdf action."""

	async def test_save_as_pdf_registered(self, tools):
		"""save_as_pdf action is in the default action registry."""
		assert 'save_as_pdf' in tools.registry.registry.actions
		action = tools.registry.registry.actions['save_as_pdf']
		assert action.function is not None
		assert 'PDF' in action.description

	async def test_save_as_pdf_default_filename(self, tools, browser_session, base_url):
		"""save_as_pdf with no filename uses the page title."""
		await tools.navigate(url=f'{base_url}/pdf-test', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		with tempfile.TemporaryDirectory() as temp_dir:
			file_system = FileSystem(temp_dir)
			result = await tools.save_as_pdf(browser_session=browser_session, file_system=file_system)

			assert isinstance(result, ActionResult)
			assert result.extracted_content is not None
			assert 'Saved page as PDF' in result.extracted_content

			attachments = _get_attachments(result)
			assert len(attachments) == 1

			pdf_path = attachments[0]
			assert pdf_path.endswith('.pdf')
			assert await anyio.Path(pdf_path).exists()

			# Verify it's actually a PDF (starts with %PDF magic bytes)
			header = await anyio.Path(pdf_path).read_bytes()
			assert header[:5] == b'%PDF-', f'File does not start with PDF magic bytes: {header[:5]!r}'

	async def test_save_as_pdf_custom_filename(self, tools, browser_session, base_url):
		"""save_as_pdf with a custom filename uses that name."""
		await tools.navigate(url=f'{base_url}/pdf-test', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		with tempfile.TemporaryDirectory() as temp_dir:
			file_system = FileSystem(temp_dir)
			result = await tools.save_as_pdf(
				file_name='my-report',
				browser_session=browser_session,
				file_system=file_system,
			)

			assert isinstance(result, ActionResult)
			attachments = _get_attachments(result)
			assert len(attachments) == 1

			pdf_path = attachments[0]
			assert 'my-report.pdf' in pdf_path
			assert await anyio.Path(pdf_path).exists()

	async def test_save_as_pdf_custom_filename_with_extension(self, tools, browser_session, base_url):
		"""save_as_pdf doesn't double the .pdf extension."""
		await tools.navigate(url=f'{base_url}/pdf-test', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		with tempfile.TemporaryDirectory() as temp_dir:
			file_system = FileSystem(temp_dir)
			result = await tools.save_as_pdf(
				file_name='already.pdf',
				browser_session=browser_session,
				file_system=file_system,
			)

			assert isinstance(result, ActionResult)
			attachments = _get_attachments(result)
			pdf_path = attachments[0]
			# Should not be "already.pdf.pdf"
			assert pdf_path.endswith('already.pdf')
			assert not pdf_path.endswith('.pdf.pdf')

	async def test_save_as_pdf_duplicate_filename(self, tools, browser_session, base_url):
		"""save_as_pdf increments filename when a duplicate exists."""
		await tools.navigate(url=f'{base_url}/pdf-test', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		with tempfile.TemporaryDirectory() as temp_dir:
			file_system = FileSystem(temp_dir)

			# Save first PDF
			result1 = await tools.save_as_pdf(
				file_name='duplicate',
				browser_session=browser_session,
				file_system=file_system,
			)
			attachments1 = _get_attachments(result1)
			assert await anyio.Path(attachments1[0]).exists()
			assert attachments1[0].endswith('duplicate.pdf')

			# Save second PDF with same name
			result2 = await tools.save_as_pdf(
				file_name='duplicate',
				browser_session=browser_session,
				file_system=file_system,
			)
			attachments2 = _get_attachments(result2)
			assert await anyio.Path(attachments2[0]).exists()
			assert 'duplicate (1).pdf' in attachments2[0]

	async def test_save_as_pdf_landscape(self, tools, browser_session, base_url):
		"""save_as_pdf with landscape=True produces a valid PDF."""
		await tools.navigate(url=f'{base_url}/pdf-test', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		with tempfile.TemporaryDirectory() as temp_dir:
			file_system = FileSystem(temp_dir)
			result = await tools.save_as_pdf(
				file_name='landscape-test',
				landscape=True,
				browser_session=browser_session,
				file_system=file_system,
			)

			assert isinstance(result, ActionResult)
			attachments = _get_attachments(result)
			assert await anyio.Path(attachments[0]).exists()

			header = await anyio.Path(attachments[0]).read_bytes()
			assert header[:5] == b'%PDF-'

	async def test_save_as_pdf_a4_format(self, tools, browser_session, base_url):
		"""save_as_pdf with paper_format='A4' produces a valid PDF."""
		await tools.navigate(url=f'{base_url}/pdf-test', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		with tempfile.TemporaryDirectory() as temp_dir:
			file_system = FileSystem(temp_dir)
			result = await tools.save_as_pdf(
				file_name='a4-test',
				paper_format='A4',
				browser_session=browser_session,
				file_system=file_system,
			)

			assert isinstance(result, ActionResult)
			attachments = _get_attachments(result)
			assert await anyio.Path(attachments[0]).exists()

	async def test_save_as_pdf_with_background(self, tools, browser_session, base_url):
		"""save_as_pdf with print_background=True on a styled page produces a valid PDF."""
		await tools.navigate(url=f'{base_url}/pdf-styled', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		with tempfile.TemporaryDirectory() as temp_dir:
			file_system = FileSystem(temp_dir)
			result = await tools.save_as_pdf(
				file_name='styled-with-bg',
				print_background=True,
				browser_session=browser_session,
				file_system=file_system,
			)

			assert isinstance(result, ActionResult)
			attachments = _get_attachments(result)
			pdf_path = attachments[0]
			assert await anyio.Path(pdf_path).exists()

			# Verify file size is non-trivial (has actual rendered content)
			stat = await anyio.Path(pdf_path).stat()
			assert stat.st_size > 1000, f'PDF seems too small ({stat.st_size} bytes), may be empty'

	async def test_save_as_pdf_param_model_schema(self):
		"""SaveAsPdfAction schema exposes the right fields with defaults."""
		from browser_use.tools.views import SaveAsPdfAction

		schema = SaveAsPdfAction.model_json_schema()
		props = schema['properties']

		assert 'file_name' in props
		assert 'print_background' in props
		assert 'landscape' in props
		assert 'scale' in props
		assert 'paper_format' in props

		# Check defaults
		assert props['print_background']['default'] is True
		assert props['landscape']['default'] is False
		assert props['scale']['default'] == 1.0
		assert props['paper_format']['default'] == 'Letter'
