import asyncio
import logging

from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.browser.services import BrowserServiceBundle
from browser_use.browser.views import BrowserError
from browser_use.dom.service import EnhancedDOMTreeNode
from browser_use.tools.dropdown import dropdown_options_action
from browser_use.tools.error_handling import handle_browser_error
from browser_use.tools.utils import get_click_description
from browser_use.tools.views import (
	ClickElementAction,
	ClickElementActionIndexOnly,
	FindTextAction,
	GetDropdownOptionsAction,
	InputTextAction,
	ScrollAction,
)
from browser_use.utils import create_task_with_error_handling

logger = logging.getLogger(__name__)


def _detect_sensitive_key_name(text: str, sensitive_data: dict[str, str | dict[str, str]] | None) -> str | None:
	"""Detect which sensitive key name corresponds to the given text value."""
	if not sensitive_data or not text:
		return None

	for domain_or_key, content in sensitive_data.items():
		if isinstance(content, dict):
			for key, value in content.items():
				if value and value == text:
					return key
		elif content and content == text:
			return domain_or_key

	return None


def _is_autocomplete_field(node: EnhancedDOMTreeNode) -> bool:
	"""Detect if a node is an autocomplete/combobox field from its attributes."""
	attrs = node.attributes or {}
	if attrs.get('role') == 'combobox':
		return True
	aria_ac = attrs.get('aria-autocomplete', '')
	if aria_ac and aria_ac != 'none':
		return True
	if attrs.get('list'):
		return True
	haspopup = attrs.get('aria-haspopup', '')
	if haspopup and haspopup != 'false' and (attrs.get('aria-controls') or attrs.get('aria-owns')):
		return True
	return False


def _convert_llm_coordinates_to_viewport(llm_x: int, llm_y: int, browser_session: BrowserSession) -> tuple[int, int]:
	"""Convert coordinates from LLM screenshot size to original viewport size."""
	if browser_session.llm_screenshot_size and browser_session._original_viewport_size:
		original_width, original_height = browser_session._original_viewport_size
		llm_width, llm_height = browser_session.llm_screenshot_size

		actual_x = int((llm_x / llm_width) * original_width)
		actual_y = int((llm_y / llm_height) * original_height)

		logger.info(
			f'🔄 Converting coordinates: LLM ({llm_x}, {llm_y}) @ {llm_width}x{llm_height} '
			f'→ Viewport ({actual_x}, {actual_y}) @ {original_width}x{original_height}'
		)
		return actual_x, actual_y
	return llm_x, llm_y


async def _detect_new_tab_opened(
	browser_session: BrowserSession,
	tabs_before: set[str],
) -> str:
	"""Detect if a click opened a new tab and automatically switch to it."""
	try:
		await asyncio.sleep(0.05)

		tabs_after = await browser_session.get_tabs()
		new_tabs = [t for t in tabs_after if t.target_id not in tabs_before]
		if new_tabs:
			new_tab = new_tabs[0]
			new_tab_id = new_tab.target_id[-4:]
			try:
				await BrowserServiceBundle.from_session(browser_session).tabs.switch(new_tab.target_id)
				return f'. Automatically switched to new tab (tab_id: {new_tab_id}).'
			except Exception:
				return f'. Note: This opened a new tab (tab_id: {new_tab_id}) - switch to it if you need to interact with the new page.'
	except Exception:
		pass
	return ''


async def click_by_coordinate_action(params: ClickElementAction, browser_session: BrowserSession) -> ActionResult:
	"""Click viewport coordinates, converting from LLM screenshot coordinates when needed."""
	if params.coordinate_x is None or params.coordinate_y is None:
		return ActionResult(error='Both coordinate_x and coordinate_y must be provided')

	try:
		actual_x, actual_y = _convert_llm_coordinates_to_viewport(params.coordinate_x, params.coordinate_y, browser_session)
		tabs_before = {t.target_id for t in await browser_session.get_tabs()}

		asyncio.create_task(browser_session.highlight_coordinate_click(actual_x, actual_y))

		click_metadata = await BrowserServiceBundle.from_session(browser_session).actions.click.click_coordinates(
			actual_x,
			actual_y,
			force=True,
		)

		if isinstance(click_metadata, dict) and 'validation_error' in click_metadata:
			return ActionResult(error=click_metadata['validation_error'])

		memory = f'Clicked on coordinate {params.coordinate_x}, {params.coordinate_y}'
		memory += await _detect_new_tab_opened(browser_session, tabs_before)
		logger.info(f'🖱️ {memory}')

		return ActionResult(
			extracted_content=memory,
			metadata={'click_x': actual_x, 'click_y': actual_y},
		)
	except BrowserError as e:
		return handle_browser_error(e)
	except Exception:
		error_msg = f'Failed to click at coordinates ({params.coordinate_x}, {params.coordinate_y}).'
		return ActionResult(error=error_msg)


async def click_by_index_action(
	params: ClickElementAction | ClickElementActionIndexOnly, browser_session: BrowserSession
) -> ActionResult:
	"""Click an indexed DOM node using the direct browser service."""
	assert params.index is not None
	try:
		assert params.index != 0, (
			'Cannot click on element with index 0. If there are no interactive elements use wait(), refresh(), etc. to troubleshoot'
		)

		node = await browser_session.get_element_by_index(params.index)
		if node is None:
			msg = f'Element index {params.index} not available - page may have changed. Try refreshing browser state.'
			logger.warning(f'⚠️ {msg}')
			return ActionResult(extracted_content=msg)

		element_desc = get_click_description(node)
		tabs_before = {t.target_id for t in await browser_session.get_tabs()}

		create_task_with_error_handling(
			browser_session.highlight_interaction_element(node), name='highlight_click_element', suppress_exceptions=True
		)

		click_metadata = await BrowserServiceBundle.from_session(browser_session).actions.click.click_index(params.index)

		if isinstance(click_metadata, dict) and 'validation_error' in click_metadata:
			error_msg = click_metadata['validation_error']
			if 'Cannot click on <select> elements.' in error_msg:
				try:
					return await dropdown_options_action(GetDropdownOptionsAction(index=params.index), browser_session)
				except Exception as dropdown_error:
					logger.debug(
						f'Failed to get dropdown options as shortcut during click on dropdown: {type(dropdown_error).__name__}: {dropdown_error}'
					)
			return ActionResult(error=error_msg)

		memory = f'Clicked {element_desc}'
		memory += await _detect_new_tab_opened(browser_session, tabs_before)
		logger.info(f'🖱️ {memory}')

		return ActionResult(
			extracted_content=memory,
			metadata=click_metadata if isinstance(click_metadata, dict) else None,
		)
	except BrowserError as e:
		return handle_browser_error(e)
	except Exception as e:
		return ActionResult(error=f'Failed to click element {params.index}: {str(e)}')


async def input_text_action(
	params: InputTextAction,
	browser_session: BrowserSession,
	*,
	has_sensitive_data: bool = False,
	sensitive_data: dict[str, str | dict[str, str]] | None = None,
) -> ActionResult:
	"""Type text into an indexed element using the direct browser service."""
	node = await browser_session.get_element_by_index(params.index)
	if node is None:
		msg = f'Element index {params.index} not available - page may have changed. Try refreshing browser state.'
		logger.warning(f'⚠️ {msg}')
		return ActionResult(extracted_content=msg)

	create_task_with_error_handling(
		browser_session.highlight_interaction_element(node), name='highlight_type_element', suppress_exceptions=True
	)

	try:
		sensitive_key_name = None
		if has_sensitive_data and sensitive_data:
			sensitive_key_name = _detect_sensitive_key_name(params.text, sensitive_data)

		input_metadata = await BrowserServiceBundle.from_session(browser_session).actions.type.type_index(
			params.index,
			params.text,
			clear=params.clear,
			is_sensitive=has_sensitive_data,
			sensitive_key_name=sensitive_key_name,
		)

		if has_sensitive_data:
			if sensitive_key_name:
				msg = f'Typed {sensitive_key_name}'
				log_msg = f'Typed <{sensitive_key_name}>'
			else:
				msg = 'Typed sensitive data'
				log_msg = 'Typed <sensitive>'
		else:
			msg = f"Typed '{params.text}'"
			log_msg = f"Typed '{params.text}'"

		logger.debug(log_msg)

		actual_value = None
		if isinstance(input_metadata, dict):
			actual_value = input_metadata.pop('actual_value', None)

		if not has_sensitive_data and actual_value is not None and actual_value != params.text:
			msg += f"\n⚠️ Note: the field's actual value '{actual_value}' differs from typed text '{params.text}'. The page may have reformatted or autocompleted your input."

		if _is_autocomplete_field(node):
			msg += '\n💡 This is an autocomplete field. Wait for suggestions to appear, then click the correct suggestion instead of pressing Enter.'
			attrs = node.attributes or {}
			if attrs.get('role') == 'combobox' or (attrs.get('aria-autocomplete', '') not in ('', 'none')):
				await asyncio.sleep(0.4)

		return ActionResult(
			extracted_content=msg,
			long_term_memory=msg,
			metadata=input_metadata if isinstance(input_metadata, dict) else None,
		)
	except BrowserError as e:
		return handle_browser_error(e)
	except Exception as e:
		logger.error(f'Failed to type through direct browser service: {type(e).__name__}: {e}')
		return ActionResult(error=f'Failed to type text into element {params.index}: {e}')


async def scroll_action(params: ScrollAction, browser_session: BrowserSession) -> ActionResult:
	"""Scroll the page or an indexed scroll container."""
	try:
		node = None
		if params.index is not None and params.index != 0:
			node = await browser_session.get_element_by_index(params.index)
			if node is None:
				return ActionResult(error=f'Element index {params.index} not found in browser state')

		direction = 'down' if params.down else 'up'
		target = f'element {params.index}' if params.index is not None and params.index != 0 else ''

		scroll_metadata = await BrowserServiceBundle.from_session(browser_session).actions.scroll.scroll_pages_with_node(
			params.pages,
			direction=direction,
			node=node,
		)
		completed_pages = scroll_metadata['completed_pages']
		viewport_height = scroll_metadata['viewport_height']
		if params.pages == 1.0:
			long_term_memory = f'Scrolled {direction} {target} {viewport_height}px'.replace('  ', ' ')
		else:
			long_term_memory = f'Scrolled {direction} {target} {completed_pages:.1f} pages'.replace('  ', ' ')

		msg = f'🔍 {long_term_memory}'
		logger.info(msg)
		return ActionResult(extracted_content=msg, long_term_memory=long_term_memory)
	except Exception as e:
		logger.error(f'Failed to scroll through direct browser service: {type(e).__name__}: {e}')
		return ActionResult(error='Failed to execute scroll action.')


async def find_text_action(params: FindTextAction, browser_session: BrowserSession) -> ActionResult:
	"""Scroll to visible page text through the direct browser service."""
	try:
		await BrowserServiceBundle.from_session(browser_session).actions.scroll.scroll_to_text(params.text)
		memory = f'Scrolled to text: {params.text}'
		msg = f'🔍  {memory}'
		logger.info(msg)
		return ActionResult(extracted_content=memory, long_term_memory=memory)
	except Exception:
		msg = f"Text '{params.text}' not found or not visible on page"
		logger.info(msg)
		return ActionResult(
			extracted_content=msg,
			long_term_memory=f"Tried scrolling to text '{params.text}' but it was not found",
		)
