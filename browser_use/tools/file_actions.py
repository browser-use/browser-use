import asyncio
import base64
import logging
import os
import re

import anyio

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.views import ReadFileAction, ReplaceFileAction, SaveAsPdfAction, ScreenshotAction, WriteFileAction

logger = logging.getLogger(__name__)


async def take_screenshot_action(
	params: ScreenshotAction,
	*,
	browser_session: BrowserSession,
	file_system: FileSystem,
) -> ActionResult:
	"""Take a screenshot, optionally saving it into the agent file system."""
	if params.file_name:
		file_name = params.file_name
		if not file_name.lower().endswith('.png'):
			file_name = f'{file_name}.png'
		file_name = FileSystem.sanitize_filename(file_name)

		screenshot_bytes = await browser_session.take_screenshot(full_page=False)
		file_path = file_system.get_dir() / file_name
		file_path.write_bytes(screenshot_bytes)

		result = f'Screenshot saved to {file_name}'
		logger.info(f'📸 {result}. Full path: {file_path}')
		return ActionResult(
			extracted_content=result,
			long_term_memory=f'{result}. Full path: {file_path}',
			attachments=[str(file_path)],
		)

	memory = 'Requested screenshot for next observation'
	logger.info(f'📸 {memory}')
	return ActionResult(
		extracted_content=memory,
		metadata={'include_screenshot': True},
	)


async def save_as_pdf_action(
	params: SaveAsPdfAction,
	*,
	browser_session: BrowserSession,
	file_system: FileSystem,
) -> ActionResult:
	"""Save the current page as a PDF using CDP Page.printToPDF."""
	paper_sizes: dict[str, tuple[float, float]] = {
		'letter': (8.5, 11),
		'legal': (8.5, 14),
		'a4': (8.27, 11.69),
		'a3': (11.69, 16.54),
		'tabloid': (11, 17),
	}

	paper_key = params.paper_format.lower()
	if paper_key not in paper_sizes:
		paper_key = 'letter'
	paper_width, paper_height = paper_sizes[paper_key]

	cdp_session = await browser_session.get_or_create_cdp_session(focus=True)

	result = await asyncio.wait_for(
		cdp_session.cdp_client.send.Page.printToPDF(
			params={
				'printBackground': params.print_background,
				'landscape': params.landscape,
				'scale': params.scale,
				'paperWidth': paper_width,
				'paperHeight': paper_height,
				'preferCSSPageSize': True,
			},
			session_id=cdp_session.session_id,
		),
		timeout=30.0,
	)

	pdf_data = result.get('data')
	assert pdf_data, 'CDP Page.printToPDF returned no data'

	pdf_bytes = base64.b64decode(pdf_data)
	file_name = await _resolve_pdf_file_name(params, browser_session)

	file_path = file_system.get_dir() / file_name
	if file_path.exists():
		base, ext = os.path.splitext(file_name)
		counter = 1
		while (file_system.get_dir() / f'{base} ({counter}){ext}').exists():
			counter += 1
		file_name = f'{base} ({counter}){ext}'
		file_path = file_system.get_dir() / file_name

	async with await anyio.open_file(file_path, 'wb') as f:
		await f.write(pdf_bytes)

	file_size = file_path.stat().st_size
	msg = f'Saved page as PDF: {file_name} ({file_size:,} bytes)'
	logger.info(f'📄 {msg}. Full path: {file_path}')

	return ActionResult(
		extracted_content=msg,
		long_term_memory=f'{msg}. Full path: {file_path}',
		attachments=[str(file_path)],
	)


async def _resolve_pdf_file_name(params: SaveAsPdfAction, browser_session: BrowserSession) -> str:
	if params.file_name:
		file_name = params.file_name
	else:
		try:
			page_title = await asyncio.wait_for(browser_session.get_current_page_title(), timeout=2.0)
			safe_title = re.sub(r'[^\w\s-]', '', page_title).strip()[:50]
			file_name = safe_title if safe_title else 'page'
		except Exception:
			file_name = 'page'

	if not file_name.lower().endswith('.pdf'):
		file_name = f'{file_name}.pdf'
	return FileSystem.sanitize_filename(file_name)


async def write_file_action(params: WriteFileAction, file_system: FileSystem) -> ActionResult:
	content = params.content
	if params.trailing_newline:
		content += '\n'
	if params.leading_newline:
		content = '\n' + content
	if params.append:
		result = await file_system.append_file(params.file_name, content)
	else:
		result = await file_system.write_file(params.file_name, content)

	resolved_name, _ = file_system._resolve_filename(params.file_name)
	file_path = file_system.get_dir() / resolved_name
	logger.info(f'💾 {result} File location: {file_path}')

	return ActionResult(extracted_content=result, long_term_memory=result)


async def replace_file_action(params: ReplaceFileAction, file_system: FileSystem) -> ActionResult:
	result = await file_system.replace_file_str(params.file_name, params.old_str, params.new_str)
	logger.info(f'💾 {result}')
	return ActionResult(extracted_content=result, long_term_memory=result)


async def read_file_action(
	params: ReadFileAction,
	*,
	available_file_paths: list[str],
	file_system: FileSystem,
) -> ActionResult:
	if available_file_paths and params.file_name in available_file_paths:
		structured_result = await file_system.read_file_structured(params.file_name, external_file=True)
	else:
		structured_result = await file_system.read_file_structured(params.file_name)

	result = structured_result['message']
	images = structured_result.get('images')

	max_memory_size = 1000
	if images:
		memory = f'Read image file {params.file_name}'
	elif len(result) > max_memory_size:
		lines = result.splitlines()
		display = ''
		lines_count = 0
		for line in lines:
			if len(display) + len(line) < max_memory_size:
				display += line + '\n'
				lines_count += 1
			else:
				break
		remaining_lines = len(lines) - lines_count
		memory = f'{display}{remaining_lines} more lines...' if remaining_lines > 0 else display
	else:
		memory = result

	logger.info(f'💾 {memory}')
	return ActionResult(
		extracted_content=result,
		long_term_memory=memory,
		images=images,
		include_extracted_content_only_once=True,
	)
