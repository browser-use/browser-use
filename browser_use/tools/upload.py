import logging
import os

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.services import BrowserServiceBundle
from browser_use.browser.views import BrowserError
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.views import UploadFileAction
from browser_use.utils import create_task_with_error_handling

logger = logging.getLogger(__name__)


async def upload_file_action(
	params: UploadFileAction,
	*,
	browser_session: BrowserSession,
	available_file_paths: list[str],
	file_system: FileSystem,
) -> ActionResult:
	"""Upload a local, downloaded, managed, or remote file through the nearest file input."""
	resolved_params = _resolve_upload_path(
		params, browser_session=browser_session, available_file_paths=available_file_paths, file_system=file_system
	)
	if isinstance(resolved_params, ActionResult):
		return resolved_params
	params = resolved_params

	if browser_session.is_local:
		if not os.path.exists(params.path):
			msg = f'File {params.path} does not exist'
			return ActionResult(error=msg)
		file_size = os.path.getsize(params.path)
		if file_size == 0:
			msg = f'File {params.path} is empty (0 bytes). The file may not have been saved correctly.'
			return ActionResult(error=msg)

	selector_map = await browser_session.get_selector_map()
	if params.index not in selector_map:
		msg = f'Element with index {params.index} does not exist.'
		return ActionResult(error=msg)

	node = selector_map[params.index]
	file_input_node = browser_session.find_file_input_near_element(node)

	if file_input_node:
		create_task_with_error_handling(
			browser_session.highlight_interaction_element(file_input_node),
			name='highlight_file_input',
			suppress_exceptions=True,
		)

	if file_input_node is None:
		logger.info(
			f'No file upload element found near index {params.index}, searching for closest file input to scroll position'
		)
		file_input_node = await _find_closest_file_input(browser_session, selector_map)
		if file_input_node:
			create_task_with_error_handling(
				browser_session.highlight_interaction_element(file_input_node),
				name='highlight_file_input_fallback',
				suppress_exceptions=True,
			)
		else:
			msg = 'No file upload element found on the page'
			logger.error(msg)
			raise BrowserError(msg)

	try:
		await BrowserServiceBundle.from_session(browser_session).actions.upload.upload_file(file_input_node, params.path)
		msg = f'Successfully uploaded file to index {params.index}'
		logger.info(f'📁 {msg}')
		return ActionResult(
			extracted_content=msg,
			long_term_memory=f'Uploaded file {params.path} to element {params.index}',
		)
	except Exception as e:
		logger.error(f'Failed to upload file: {e}')
		raise BrowserError(f'Failed to upload file: {e}')


def _resolve_upload_path(
	params: UploadFileAction,
	*,
	browser_session: BrowserSession,
	available_file_paths: list[str],
	file_system: FileSystem,
) -> UploadFileAction | ActionResult:
	if params.path in available_file_paths or params.path in browser_session.downloaded_files:
		return params

	if browser_session.is_local and file_system and file_system.get_dir():
		file_obj = file_system.get_file(params.path)
		if file_obj:
			file_system_path = str(file_system.get_dir() / file_obj.full_name)
			real_path = os.path.realpath(file_system_path)
			real_dir = os.path.realpath(str(file_system.get_dir()))
			if not (real_path == real_dir or real_path.startswith(real_dir + os.sep)):
				msg = f'Upload of {params.path!r} escapes FileSystem directory; refusing.'
				logger.error(f'❌ {msg}')
				return ActionResult(error=msg)
			return UploadFileAction(index=params.index, path=file_system_path)

		msg = (
			f'File path {params.path} is not available. To fix: The user must add this file path to the '
			f'available_file_paths parameter when creating the Agent. Example: Agent(task="...", llm=llm, '
			f'browser=browser, available_file_paths=["{params.path}"])'
		)
		logger.error(f'❌ {msg}')
		return ActionResult(error=msg)

	if not browser_session.is_local:
		return params

	msg = (
		f'File path {params.path} is not available. To fix: The user must add this file path to the available_file_paths '
		f'parameter when creating the Agent. Example: Agent(task="...", llm=llm, browser=browser, '
		f'available_file_paths=["{params.path}"])'
	)
	raise BrowserError(message=msg, long_term_memory=msg)


async def _find_closest_file_input(browser_session: BrowserSession, selector_map: dict):
	cdp_session = await browser_session.get_or_create_cdp_session()
	try:
		scroll_info = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'window.scrollY || window.pageYOffset || 0'},
			session_id=cdp_session.session_id,
		)
		current_scroll_y = scroll_info.get('result', {}).get('value', 0)
	except Exception:
		current_scroll_y = 0

	closest_file_input = None
	min_distance = float('inf')

	for element in selector_map.values():
		if browser_session.is_file_input(element) and element.absolute_position:
			element_y = element.absolute_position.y
			distance = abs(element_y - current_scroll_y)
			if distance < min_distance:
				min_distance = distance
				closest_file_input = element

	if closest_file_input:
		logger.info(f'Found file input closest to scroll position (distance: {min_distance}px)')

	return closest_file_input
