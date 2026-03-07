"""Browser control commands."""

import asyncio
import base64
import logging
import tempfile
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, cast

from browser_use.skill_cli.sessions import SessionInfo

logger = logging.getLogger(__name__)

COMMANDS = {
	'open',
	'click',
	'type',
	'input',
	'scroll',
	'back',
	'screenshot',
	'state',
	'switch',
	'close-tab',
	'keys',
	'select',
	'eval',
	'extract',
	'cookies',
	'wait',
	'hover',
	'dblclick',
	'rightclick',
	'get',
}


def _is_safari_backend(browser_session: Any) -> bool:
	"""Whether the current browser session uses the Safari backend."""
	return bool(getattr(browser_session, 'is_safari_backend', False))


async def _dispatch_event_and_require_success(event: Any) -> Any:
	"""Await a Bubus event and surface handler failures to the CLI."""
	await cast(Awaitable[Any], event)
	event_result = getattr(event, 'event_result', None)
	if callable(event_result):
		await cast(Awaitable[Any], event_result(raise_if_any=True, raise_if_none=False))
	return event


async def _execute_js(session: SessionInfo, js: str) -> Any:
	"""Execute JavaScript in the browser."""
	bs = session.browser_session
	if hasattr(bs, 'evaluate_javascript'):
		return await bs.evaluate_javascript(js)
	# Get or create a CDP session for the focused target
	cdp_session = await bs.get_or_create_cdp_session(target_id=None, focus=False)
	if not cdp_session:
		raise RuntimeError('No active browser session')

	result = await cdp_session.cdp_client.send.Runtime.evaluate(
		params={'expression': js, 'returnByValue': True},
		session_id=cdp_session.session_id,
	)
	return result.get('result', {}).get('value')


async def _get_element_center(session: SessionInfo, node: Any) -> tuple[float, float] | None:
	"""Get the center coordinates of an element."""
	bs = session.browser_session
	absolute_position = getattr(node, 'absolute_position', None)
	if absolute_position is not None:
		return absolute_position.x + absolute_position.width / 2, absolute_position.y + absolute_position.height / 2
	try:
		cdp_session = await bs.cdp_client_for_node(node)
		session_id = cdp_session.session_id
		backend_node_id = node.backend_node_id

		# Scroll element into view first
		try:
			await cdp_session.cdp_client.send.DOM.scrollIntoViewIfNeeded(
				params={'backendNodeId': backend_node_id}, session_id=session_id
			)
			await asyncio.sleep(0.05)
		except Exception:
			pass

		# Get element coordinates
		element_rect = await bs.get_element_coordinates(backend_node_id, cdp_session)
		if element_rect:
			center_x = element_rect.x + element_rect.width / 2
			center_y = element_rect.y + element_rect.height / 2
			return center_x, center_y
		return None
	except Exception as e:
		logger.error(f'Failed to get element center: {e}')
		return None


async def _extract_page_data(
	session: SessionInfo,
	query: str,
	output_schema: dict[str, Any] | None = None,
	extract_links: bool = False,
	start_from_char: int = 0,
) -> Any:
	"""Extract page data using the configured CLI LLM."""
	from browser_use.agent.views import ActionResult
	from browser_use.filesystem.file_system import FileSystem
	from browser_use.skill_cli.commands.agent import get_llm
	from browser_use.tools.service import Tools

	page_extraction_llm = get_llm()
	if page_extraction_llm is None:
		raise RuntimeError(
			'No LLM configured for browser.extract(). '
			'Set BROWSER_USE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY.'
		)

	with tempfile.TemporaryDirectory(prefix='browser-use-cli-extract-') as tmp:
		file_system = FileSystem(tmp)
		tools = Tools()
		result = await tools.extract(
			query=query,
			extract_links=extract_links,
			start_from_char=start_from_char,
			output_schema=output_schema,
			browser_session=session.browser_session,
			page_extraction_llm=page_extraction_llm,
			file_system=file_system,
		)

	assert isinstance(result, ActionResult)
	if result.error:
		raise RuntimeError(result.error)

	if output_schema is not None and result.metadata:
		extraction_result = result.metadata.get('extraction_result')
		if isinstance(extraction_result, dict) and 'data' in extraction_result:
			return extraction_result['data']

	if result.extracted_content is not None:
		return result.extracted_content
	return result.long_term_memory


async def _get_element_value(session: SessionInfo, node: Any) -> Any:
	"""Read the current value/text content for an indexed element."""
	bs = session.browser_session
	if _is_safari_backend(bs):
		return await bs.evaluate_javascript(
			f"""
			(() => {{
				const el = document.querySelector('[data-browser-use-safari-id="{node.backend_node_id}"]');
				if (!el) return null;
				if ('value' in el) return el.value;
				if (el.isContentEditable) return el.textContent || '';
				return el.getAttribute('value') || '';
			}})()
			"""
		)

	cdp_session = await bs.cdp_client_for_node(node)
	resolve_result = await cdp_session.cdp_client.send.DOM.resolveNode(
		params={'backendNodeId': node.backend_node_id},
		session_id=cdp_session.session_id,
	)
	object_id = resolve_result['object'].get('objectId')  # type: ignore[union-attr]

	if not object_id:
		return ''

	value_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
		params={
			'objectId': object_id,
			'functionDeclaration': 'function() { return this.value; }',
			'returnByValue': True,
		},
		session_id=cdp_session.session_id,
	)
	return value_result.get('result', {}).get('value')


async def _get_element_bbox(session: SessionInfo, node: Any) -> dict[str, float]:
	"""Read the current bounding box for an indexed element."""
	bs = session.browser_session
	if _is_safari_backend(bs):
		absolute_position = getattr(node, 'absolute_position', None)
		if absolute_position is not None:
			return {
				'x': absolute_position.x,
				'y': absolute_position.y,
				'width': absolute_position.width,
				'height': absolute_position.height,
			}

		result = await bs.evaluate_javascript(
			f"""
			(() => {{
				const el = document.querySelector('[data-browser-use-safari-id="{node.backend_node_id}"]');
				if (!el) return null;
				const rect = el.getBoundingClientRect();
				return {{
					x: rect.left + window.scrollX,
					y: rect.top + window.scrollY,
					width: rect.width,
					height: rect.height,
				}};
			}})()
			"""
		)
		return result if isinstance(result, dict) else {}

	cdp_session = await bs.cdp_client_for_node(node)
	box_result = await cdp_session.cdp_client.send.DOM.getBoxModel(
		params={'backendNodeId': node.backend_node_id},
		session_id=cdp_session.session_id,
	)

	model = box_result['model']  # type: ignore[index]
	content = model.get('content', [])  # type: ignore[union-attr]

	if len(content) < 8:
		return {}

	x = min(content[0], content[2], content[4], content[6])
	y = min(content[1], content[3], content[5], content[7])
	width = max(content[0], content[2], content[4], content[6]) - x
	height = max(content[1], content[3], content[5], content[7]) - y
	return {'x': x, 'y': y, 'width': width, 'height': height}


async def _get_element_text(session: SessionInfo, node: Any) -> str:
	"""Read the current rendered text for an indexed element."""
	bs = session.browser_session
	snapshot_text = node.get_all_children_text(max_depth=10) if node else ''
	if _is_safari_backend(bs):
		result = await bs.evaluate_javascript(
			f"""
			(() => {{
				const el = document.querySelector('[data-browser-use-safari-id="{node.backend_node_id}"]');
				if (!el) return null;
				return el.innerText || el.textContent || '';
			}})()
			"""
		)
		return result if isinstance(result, str) else snapshot_text

	cdp_session = await bs.cdp_client_for_node(node)
	resolve_result = await cdp_session.cdp_client.send.DOM.resolveNode(
		params={'backendNodeId': node.backend_node_id},
		session_id=cdp_session.session_id,
	)
	object_id = resolve_result['object'].get('objectId')  # type: ignore[union-attr]
	if not object_id:
		return snapshot_text

	text_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
		params={
			'objectId': object_id,
			'functionDeclaration': 'function() { return this.innerText || this.textContent || ""; }',
			'returnByValue': True,
		},
		session_id=cdp_session.session_id,
	)
	value = text_result.get('result', {}).get('value')
	return value if isinstance(value, str) else snapshot_text


async def _get_element_attributes(session: SessionInfo, node: Any) -> dict[str, Any]:
	"""Read the current attributes for an indexed element."""
	bs = session.browser_session
	snapshot_attrs = dict(node.attributes or {})
	if _is_safari_backend(bs):
		result = await bs.evaluate_javascript(
			f"""
			(() => {{
				const el = document.querySelector('[data-browser-use-safari-id="{node.backend_node_id}"]');
				if (!el) return null;
				return Object.fromEntries(Array.from(el.attributes).map(attr => [attr.name, attr.value]));
			}})()
			"""
		)
		return result if isinstance(result, dict) else snapshot_attrs

	cdp_session = await bs.cdp_client_for_node(node)
	resolve_result = await cdp_session.cdp_client.send.DOM.resolveNode(
		params={'backendNodeId': node.backend_node_id},
		session_id=cdp_session.session_id,
	)
	object_id = resolve_result['object'].get('objectId')  # type: ignore[union-attr]
	if not object_id:
		return snapshot_attrs

	attrs_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
		params={
			'objectId': object_id,
			'functionDeclaration': 'function() { return Object.fromEntries(Array.from(this.attributes || []).map(attr => [attr.name, attr.value])); }',
			'returnByValue': True,
		},
		session_id=cdp_session.session_id,
	)
	value = attrs_result.get('result', {}).get('value')
	return value if isinstance(value, dict) else snapshot_attrs


async def handle(action: str, session: SessionInfo, params: dict[str, Any]) -> Any:
	"""Handle browser control command."""
	bs = session.browser_session

	if action == 'open':
		url = params['url']
		# Ensure URL has scheme
		if not url.startswith(('http://', 'https://', 'file://')):
			url = 'https://' + url

		from browser_use.browser.events import NavigateToUrlEvent

		await _dispatch_event_and_require_success(bs.event_bus.dispatch(NavigateToUrlEvent(url=url)))
		result: dict[str, Any] = {'url': url}
		# Add live preview URL for cloud browsers
		if bs.browser_profile.use_cloud and bs.cdp_url:
			from urllib.parse import quote

			result['live_url'] = f'https://live.browser-use.com/?wss={quote(bs.cdp_url, safe="")}'
		return result

	elif action == 'click':
		args = params.get('args', [])
		if len(args) == 2:
			# Coordinate click: browser-use click <x> <y>
			from browser_use.browser.events import ClickCoordinateEvent

			x, y = args
			await _dispatch_event_and_require_success(bs.event_bus.dispatch(ClickCoordinateEvent(coordinate_x=x, coordinate_y=y)))
			return {'clicked_coordinate': {'x': x, 'y': y}}
		elif len(args) == 1:
			# Index click: browser-use click <index>
			from browser_use.browser.events import ClickElementEvent

			index = args[0]
			node = await bs.get_element_by_index(index)
			if node is None:
				return {'error': f'Element index {index} not found - page may have changed'}
			await _dispatch_event_and_require_success(bs.event_bus.dispatch(ClickElementEvent(node=node)))
			return {'clicked': index}
		else:
			return {'error': 'Usage: click <index> or click <x> <y>'}

	elif action == 'type':
		text = params['text']
		if _is_safari_backend(bs):
			from browser_use.browser.events import SendKeysEvent

			await _dispatch_event_and_require_success(bs.event_bus.dispatch(SendKeysEvent(keys=text)))
			return {'typed': text}

		# Type into currently focused element using CDP directly
		cdp_session = await bs.get_or_create_cdp_session(target_id=None, focus=False)
		if not cdp_session:
			return {'error': 'No active browser session'}
		await cdp_session.cdp_client.send.Input.insertText(
			params={'text': text},
			session_id=cdp_session.session_id,
		)
		return {'typed': text}

	elif action == 'input':
		from browser_use.browser.events import ClickElementEvent, TypeTextEvent

		index = params['index']
		text = params['text']
		# Look up node from selector map
		node = await bs.get_element_by_index(index)
		if node is None:
			return {'error': f'Element index {index} not found - page may have changed'}
		await _dispatch_event_and_require_success(bs.event_bus.dispatch(ClickElementEvent(node=node)))
		await _dispatch_event_and_require_success(bs.event_bus.dispatch(TypeTextEvent(node=node, text=text)))
		return {'input': text, 'element': index}

	elif action == 'scroll':
		from browser_use.browser.events import ScrollEvent

		direction = params.get('direction', 'down')
		amount = params.get('amount', 500)
		await _dispatch_event_and_require_success(bs.event_bus.dispatch(ScrollEvent(direction=direction, amount=amount)))
		return {'scrolled': direction, 'amount': amount}

	elif action == 'back':
		from browser_use.browser.events import GoBackEvent

		await _dispatch_event_and_require_success(bs.event_bus.dispatch(GoBackEvent()))
		return {'back': True}

	elif action == 'screenshot':
		data = await bs.take_screenshot(full_page=params.get('full', False))

		if params.get('path'):
			path = Path(params['path'])
			path.write_bytes(data)
			return {'saved': str(path), 'size': len(data)}

		# Return base64 encoded
		return {'screenshot': base64.b64encode(data).decode(), 'size': len(data)}

	elif action == 'state':
		# Return the LLM representation with viewport info for coordinate clicking
		state = await bs.get_browser_state_summary()
		assert state.dom_state is not None
		state_text = state.dom_state.llm_representation()

		# Prepend viewport dimensions so LLMs know the coordinate space
		if state.page_info:
			pi = state.page_info
			viewport_text = f'viewport: {pi.viewport_width}x{pi.viewport_height}\n'
			viewport_text += f'page: {pi.page_width}x{pi.page_height}\n'
			viewport_text += f'scroll: ({pi.scroll_x}, {pi.scroll_y})\n'
			state_text = viewport_text + state_text

		return {'_raw_text': state_text}

	elif action == 'switch':
		from browser_use.browser.events import SwitchTabEvent

		tab_index = params['tab']
		tabs = await bs.get_tabs()
		if tab_index < 0 or tab_index >= len(tabs):
			return {'error': f'Invalid tab index {tab_index}. Available: 0-{len(tabs) - 1}'}
		target_id = tabs[tab_index].target_id
		await _dispatch_event_and_require_success(bs.event_bus.dispatch(SwitchTabEvent(target_id=target_id)))
		return {'switched': tab_index}

	elif action == 'close-tab':
		from browser_use.browser.events import CloseTabEvent

		tab_index = params.get('tab')
		tabs = await bs.get_tabs()
		if tab_index is not None:
			if tab_index < 0 or tab_index >= len(tabs):
				return {'error': f'Invalid tab index {tab_index}. Available: 0-{len(tabs) - 1}'}
			target_id = tabs[tab_index].target_id
		else:
			# Close current/focused tab
			target_id = getattr(bs, 'agent_focus_target_id', None)
			if not target_id:
				return {'error': 'No focused tab to close'}
		await _dispatch_event_and_require_success(bs.event_bus.dispatch(CloseTabEvent(target_id=target_id)))
		return {'closed': tab_index}

	elif action == 'keys':
		from browser_use.browser.events import SendKeysEvent

		keys = params['keys']
		await _dispatch_event_and_require_success(bs.event_bus.dispatch(SendKeysEvent(keys=keys)))
		return {'sent': keys}

	elif action == 'select':
		from browser_use.browser.events import SelectDropdownOptionEvent

		index = params['index']
		value = params['value']
		# Look up node from selector map
		node = await bs.get_element_by_index(index)
		if node is None:
			return {'error': f'Element index {index} not found - page may have changed'}
		await _dispatch_event_and_require_success(bs.event_bus.dispatch(SelectDropdownOptionEvent(node=node, text=value)))
		return {'selected': value, 'element': index}

	elif action == 'eval':
		js = params['js']
		# Execute JavaScript via CDP
		result = await _execute_js(session, js)
		return {'result': result}

	elif action == 'extract':
		query = params['query']
		result = await _extract_page_data(
			session,
			query=query,
			output_schema=params.get('output_schema'),
			extract_links=params.get('extract_links', False),
			start_from_char=params.get('start_from_char', 0),
		)
		return {'query': query, 'result': result}

	elif action == 'hover':
		index = params['index']
		node = await bs.get_element_by_index(index)
		if node is None:
			return {'error': f'Element index {index} not found - page may have changed'}

		if _is_safari_backend(bs):
			backend = getattr(bs, '_backend', None)
			if backend is None or not hasattr(backend, 'hover_element'):
				return {'error': 'Safari backend is not ready for hover yet'}
			result = await backend.hover_element(node)
			if isinstance(result, dict) and result.get('ok') is False:
				return {'error': f'Safari hover failed: {result.get("error", "unknown_error")}'}
			return {'hovered': index}

		coords = await _get_element_center(session, node)
		if not coords:
			return {'error': 'Could not get element coordinates for hover'}

		center_x, center_y = coords
		cdp_session = await bs.cdp_client_for_node(node)
		await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
			params={'type': 'mouseMoved', 'x': center_x, 'y': center_y},
			session_id=cdp_session.session_id,
		)
		return {'hovered': index}

	elif action == 'dblclick':
		index = params['index']
		node = await bs.get_element_by_index(index)
		if node is None:
			return {'error': f'Element index {index} not found - page may have changed'}

		if _is_safari_backend(bs):
			backend = getattr(bs, '_backend', None)
			if backend is None or not hasattr(backend, 'double_click_element'):
				return {'error': 'Safari backend is not ready for double-click yet'}
			result = await backend.double_click_element(node)
			if isinstance(result, dict) and result.get('ok') is False:
				return {'error': f'Safari double-click failed: {result.get("error", "unknown_error")}'}
			return {'double_clicked': index}

		coords = await _get_element_center(session, node)
		if not coords:
			return {'error': 'Could not get element coordinates for double-click'}

		center_x, center_y = coords
		cdp_session = await bs.cdp_client_for_node(node)
		session_id = cdp_session.session_id

		# Move mouse to element
		await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
			params={'type': 'mouseMoved', 'x': center_x, 'y': center_y},
			session_id=session_id,
		)
		await asyncio.sleep(0.05)

		# Double click (clickCount: 2)
		await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
			params={
				'type': 'mousePressed',
				'x': center_x,
				'y': center_y,
				'button': 'left',
				'clickCount': 2,
			},
			session_id=session_id,
		)
		await asyncio.sleep(0.05)

		await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
			params={
				'type': 'mouseReleased',
				'x': center_x,
				'y': center_y,
				'button': 'left',
				'clickCount': 2,
			},
			session_id=session_id,
		)
		return {'double_clicked': index}

	elif action == 'rightclick':
		index = params['index']
		node = await bs.get_element_by_index(index)
		if node is None:
			return {'error': f'Element index {index} not found - page may have changed'}

		if _is_safari_backend(bs):
			backend = getattr(bs, '_backend', None)
			if backend is None or not hasattr(backend, 'click_element'):
				return {'error': 'Safari backend is not ready for right-click yet'}
			result = await backend.click_element(node, button='right')
			if isinstance(result, dict) and result.get('ok') is False:
				return {'error': f'Safari right-click failed: {result.get("error", "unknown_error")}'}
			return {'right_clicked': index}

		coords = await _get_element_center(session, node)
		if not coords:
			return {'error': 'Could not get element coordinates for right-click'}

		center_x, center_y = coords
		cdp_session = await bs.cdp_client_for_node(node)
		session_id = cdp_session.session_id

		# Move mouse to element
		await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
			params={'type': 'mouseMoved', 'x': center_x, 'y': center_y},
			session_id=session_id,
		)
		await asyncio.sleep(0.05)

		# Right click (button: 'right')
		await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
			params={
				'type': 'mousePressed',
				'x': center_x,
				'y': center_y,
				'button': 'right',
				'clickCount': 1,
			},
			session_id=session_id,
		)
		await asyncio.sleep(0.05)

		await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
			params={
				'type': 'mouseReleased',
				'x': center_x,
				'y': center_y,
				'button': 'right',
				'clickCount': 1,
			},
			session_id=session_id,
		)
		return {'right_clicked': index}

	elif action == 'cookies':
		if _is_safari_backend(bs):
			return {'error': 'Safari backend does not expose cookies through the CLI'}

		cookies_command = params.get('cookies_command')

		if cookies_command == 'get':
			# Get cookies via direct CDP
			cookies = await bs._cdp_get_cookies()
			# Convert Cookie objects to dicts
			cookie_list: list[dict[str, Any]] = []
			for c in cookies:
				cookie_dict: dict[str, Any] = {
					'name': c.get('name', ''),
					'value': c.get('value', ''),
					'domain': c.get('domain', ''),
					'path': c.get('path', '/'),
					'secure': c.get('secure', False),
					'httpOnly': c.get('httpOnly', False),
				}
				if 'sameSite' in c:
					cookie_dict['sameSite'] = c.get('sameSite')
				if 'expires' in c:
					cookie_dict['expires'] = c.get('expires')
				cookie_list.append(cookie_dict)

			# Filter by URL if provided
			url = params.get('url')
			if url:
				from urllib.parse import urlparse

				parsed = urlparse(url)
				domain = parsed.netloc
				cookie_list = [
					c
					for c in cookie_list
					if domain.endswith(str(c.get('domain', '')).lstrip('.'))
					or str(c.get('domain', '')).lstrip('.').endswith(domain)
				]

			return {'cookies': cookie_list}

		elif cookies_command == 'set':
			from cdp_use.cdp.network import Cookie

			cookie_dict: dict[str, Any] = {
				'name': params['name'],
				'value': params['value'],
				'path': params.get('path', '/'),
				'secure': params.get('secure', False),
				'httpOnly': params.get('http_only', False),
			}

			if params.get('domain'):
				cookie_dict['domain'] = params['domain']
			if params.get('same_site'):
				cookie_dict['sameSite'] = params['same_site']
			if params.get('expires'):
				cookie_dict['expires'] = params['expires']

			# If no domain specified, get current URL's domain
			if not params.get('domain'):
				hostname = await _execute_js(session, 'window.location.hostname')
				if hostname:
					cookie_dict['domain'] = hostname

			try:
				cookie_obj = Cookie(**cookie_dict)
				await bs._cdp_set_cookies([cookie_obj])
				return {'set': params['name'], 'success': True}
			except Exception as e:
				logger.error(f'Failed to set cookie: {e}')
				return {'set': params['name'], 'success': False, 'error': str(e)}

		elif cookies_command == 'clear':
			url = params.get('url')
			if url:
				# Clear cookies only for specific URL domain
				from urllib.parse import urlparse

				cookies = await bs._cdp_get_cookies()
				parsed = urlparse(url)
				domain = parsed.netloc

				cdp_session = await bs.get_or_create_cdp_session(target_id=None, focus=False)
				if cdp_session:
					for cookie in cookies:
						cookie_domain = str(cookie.get('domain', '')).lstrip('.')
						if domain.endswith(cookie_domain) or cookie_domain.endswith(domain):
							await cdp_session.cdp_client.send.Network.deleteCookies(
								params={
									'name': cookie.get('name', ''),
									'domain': cookie.get('domain'),
									'path': cookie.get('path', '/'),
								},
								session_id=cdp_session.session_id,
							)
			else:
				# Clear all cookies
				await bs._cdp_clear_cookies()

			return {'cleared': True, 'url': url}

		elif cookies_command == 'export':
			import json

			# Get cookies via direct CDP
			cookies = await bs._cdp_get_cookies()
			# Convert to list of dicts
			cookie_list: list[dict[str, Any]] = []
			for c in cookies:
				cookie_dict: dict[str, Any] = {
					'name': c.get('name', ''),
					'value': c.get('value', ''),
					'domain': c.get('domain', ''),
					'path': c.get('path', '/'),
					'secure': c.get('secure', False),
					'httpOnly': c.get('httpOnly', False),
				}
				if 'sameSite' in c:
					cookie_dict['sameSite'] = c.get('sameSite')
				if 'expires' in c:
					cookie_dict['expires'] = c.get('expires')
				cookie_list.append(cookie_dict)

			# Filter by URL if provided
			url = params.get('url')
			if url:
				from urllib.parse import urlparse

				parsed = urlparse(url)
				domain = parsed.netloc
				cookie_list = [
					c
					for c in cookie_list
					if domain.endswith(str(c.get('domain', '')).lstrip('.'))
					or str(c.get('domain', '')).lstrip('.').endswith(domain)
				]

			file_path = Path(params['file'])
			file_path.write_text(json.dumps(cookie_list, indent=2, ensure_ascii=False), encoding='utf-8')
			return {'exported': len(cookie_list), 'file': str(file_path)}

		elif cookies_command == 'import':
			import json

			file_path = Path(params['file'])
			if not file_path.exists():
				return {'error': f'File not found: {file_path}'}

			cookies = json.loads(file_path.read_text())

			# Get CDP session for bulk cookie setting
			cdp_session = await bs.get_or_create_cdp_session(target_id=None, focus=False)
			if not cdp_session:
				return {'error': 'No active browser session'}

			# Build cookie list for bulk set
			cookie_list = []
			for c in cookies:
				cookie_params = {
					'name': c['name'],
					'value': c['value'],
					'domain': c.get('domain'),
					'path': c.get('path', '/'),
					'secure': c.get('secure', False),
					'httpOnly': c.get('httpOnly', False),
				}
				if c.get('sameSite'):
					cookie_params['sameSite'] = c['sameSite']
				if c.get('expires'):
					cookie_params['expires'] = c['expires']
				cookie_list.append(cookie_params)

			# Set all cookies in one call
			try:
				await cdp_session.cdp_client.send.Network.setCookies(
					params={'cookies': cookie_list},  # type: ignore[arg-type]
					session_id=cdp_session.session_id,
				)
				return {'imported': len(cookie_list), 'file': str(file_path)}
			except Exception as e:
				return {'error': f'Failed to import cookies: {e}'}

		return {'error': 'Invalid cookies command. Use: get, set, clear, export, import'}

	elif action == 'wait':
		import json as json_module

		wait_command = params.get('wait_command')

		if wait_command == 'selector':
			timeout_seconds = params.get('timeout', 30000) / 1000.0
			state = params.get('state', 'visible')
			selector = params['selector']
			poll_interval = 0.1
			elapsed = 0.0

			while elapsed < timeout_seconds:
				# Build JS check based on state
				if state == 'attached':
					js = f'document.querySelector({json_module.dumps(selector)}) !== null'
				elif state == 'detached':
					js = f'document.querySelector({json_module.dumps(selector)}) === null'
				elif state == 'visible':
					js = f"""
						(function() {{
							const el = document.querySelector({json_module.dumps(selector)});
							if (!el) return false;
							const style = window.getComputedStyle(el);
							const rect = el.getBoundingClientRect();
							return style.display !== 'none' &&
								   style.visibility !== 'hidden' &&
								   style.opacity !== '0' &&
								   rect.width > 0 &&
								   rect.height > 0;
						}})()
					"""
				elif state == 'hidden':
					js = f"""
						(function() {{
							const el = document.querySelector({json_module.dumps(selector)});
							if (!el) return true;
							const style = window.getComputedStyle(el);
							const rect = el.getBoundingClientRect();
							return style.display === 'none' ||
								   style.visibility === 'hidden' ||
								   style.opacity === '0' ||
								   rect.width === 0 ||
								   rect.height === 0;
						}})()
					"""
				else:
					js = f'document.querySelector({json_module.dumps(selector)}) !== null'

				result = await _execute_js(session, js)
				if result:
					return {'selector': selector, 'found': True}

				await asyncio.sleep(poll_interval)
				elapsed += poll_interval

			return {'selector': selector, 'found': False}

		elif wait_command == 'text':
			import json as json_module

			timeout_seconds = params.get('timeout', 30000) / 1000.0
			text = params['text']
			poll_interval = 0.1
			elapsed = 0.0

			while elapsed < timeout_seconds:
				js = f"""
					(function() {{
						const text = {json_module.dumps(text)};
						return document.body.innerText.includes(text);
					}})()
				"""
				result = await _execute_js(session, js)
				if result:
					return {'text': text, 'found': True}

				await asyncio.sleep(poll_interval)
				elapsed += poll_interval

			return {'text': text, 'found': False}

		return {'error': 'Invalid wait command. Use: selector, text'}

	elif action == 'get':
		import json as json_module

		get_command = params.get('get_command')

		if get_command == 'title':
			title = await _execute_js(session, 'document.title')
			return {'title': title or ''}

		elif get_command == 'html':
			selector = params.get('selector')
			if selector:
				js = f'(function(){{ const el = document.querySelector({json_module.dumps(selector)}); return el ? el.outerHTML : null; }})()'
			else:
				js = 'document.documentElement.outerHTML'
			html = await _execute_js(session, js)
			return {'html': html or ''}

		elif get_command == 'text':
			index = params['index']
			node = await bs.get_element_by_index(index)
			if node is None:
				return {'error': f'Element index {index} not found - page may have changed'}
			try:
				text = await _get_element_text(session, node)
				return {'index': index, 'text': text}
			except Exception as e:
				logger.error(f'Failed to get element text: {e}')
				return {'index': index, 'text': node.get_all_children_text(max_depth=10) if node else ''}

		elif get_command == 'value':
			index = params['index']
			node = await bs.get_element_by_index(index)
			if node is None:
				return {'error': f'Element index {index} not found - page may have changed'}

			try:
				value = await _get_element_value(session, node)
				return {'index': index, 'value': value or ''}
			except Exception as e:
				logger.error(f'Failed to get element value: {e}')
				return {'index': index, 'value': ''}

		elif get_command == 'attributes':
			index = params['index']
			node = await bs.get_element_by_index(index)
			if node is None:
				return {'error': f'Element index {index} not found - page may have changed'}
			try:
				attrs = await _get_element_attributes(session, node)
				return {'index': index, 'attributes': attrs}
			except Exception as e:
				logger.error(f'Failed to get element attributes: {e}')
				return {'index': index, 'attributes': dict(node.attributes or {})}

		elif get_command == 'bbox':
			index = params['index']
			node = await bs.get_element_by_index(index)
			if node is None:
				return {'error': f'Element index {index} not found - page may have changed'}

			try:
				bbox = await _get_element_bbox(session, node)
				return {'index': index, 'bbox': bbox}
			except Exception as e:
				logger.error(f'Failed to get element bbox: {e}')
				return {'index': index, 'bbox': {}}

		return {'error': 'Invalid get command. Use: title, html, text, value, attributes, bbox'}

	raise ValueError(f'Unknown browser action: {action}')
