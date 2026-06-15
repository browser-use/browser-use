"""Browser control commands."""

import asyncio
import base64
import logging
from pathlib import Path
from typing import Any

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
	'tab',
	'keys',
	'select',
	'upload',
	'eval',
	'extract',
	'cookies',
	'wait',
	'hover',
	'dblclick',
	'rightclick',
	'get',
	'record',
}


async def _execute_js(session: SessionInfo, js: str) -> Any:
	"""Execute JavaScript in the browser via CDP."""
	bs = session.browser_session
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


async def handle(action: str, session: SessionInfo, params: dict[str, Any]) -> Any:
	"""Handle browser control command."""
	bs = session.browser_session
	actions = session.actions
	if actions is None:
		return {'error': 'ActionHandler not initialized'}

	if action == 'open':
		url = params['url']
		if not url.startswith(('http://', 'https://', 'file://')):
			url = 'https://' + url
		await actions.navigate(url)
		result: dict[str, Any] = {'url': url}
		if bs.browser_profile.use_cloud and bs.cdp_url:
			from urllib.parse import quote

			result['live_url'] = f'https://live.browser-use.com/?wss={quote(bs.cdp_url, safe="")}'
		return result

	elif action == 'click':
		args = params.get('args', [])
		if len(args) == 2:
			x, y = args
			await actions.click_coordinate(x, y)
			return {'clicked_coordinate': {'x': x, 'y': y}}
		elif len(args) == 1:
			index = args[0]
			node = await bs.get_element_by_index(index)
			if node is None:
				return {'error': f'Element index {index} not found - page may have changed'}
			await actions.click_element(node)
			return {'clicked': index}
		else:
			return {'error': 'Usage: click <index> or click <x> <y>'}

	elif action == 'type':
		text = params['text']
		cdp_session = await bs.get_or_create_cdp_session(target_id=None, focus=False)
		if not cdp_session:
			return {'error': 'No active browser session'}
		await cdp_session.cdp_client.send.Input.insertText(
			params={'text': text},
			session_id=cdp_session.session_id,
		)
		return {'typed': text}

	elif action == 'input':
		index = params['index']
		text = params['text']
		node = await bs.get_element_by_index(index)
		if node is None:
			return {'error': f'Element index {index} not found - page may have changed'}
		await actions.click_element(node)
		await actions.type_text(node, text)
		return {'input': text, 'element': index}

	elif action == 'scroll':
		direction = params.get('direction', 'down')
		amount = params.get('amount', 500)
		await actions.scroll(direction, amount)
		return {'scrolled': direction, 'amount': amount}

	elif action == 'back':
		await actions.go_back()
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
		state = await actions.get_state()
		assert state.dom_state is not None
		state_text = state.dom_state.llm_representation()

		# Prepend viewport dimensions
		if state.page_info:
			pi = state.page_info
			viewport_text = f'viewport: {pi.viewport_width}x{pi.viewport_height}\n'
			viewport_text += f'page: {pi.page_width}x{pi.page_height}\n'
			viewport_text += f'scroll: ({pi.scroll_x}, {pi.scroll_y})\n'
			state_text = viewport_text + state_text

		# Append auto-dismissed popup messages
		if bs._closed_popup_messages:
			state_text += '\nAuto-closed dialogs:\n'
			for msg in bs._closed_popup_messages:
				state_text += f'  {msg}\n'
			bs._closed_popup_messages.clear()

		return {'_raw_text': state_text}

	elif action == 'tab':
		tab_command = params.get('tab_command')

		if tab_command == 'list':
			page_targets = bs.session_manager.get_all_page_targets() if bs.session_manager else []
			lines = ['TAB  URL']
			for i, t in enumerate(page_targets):
				lines.append(f'{i:<4} {t.url}')
			return {'_raw_text': '\n'.join(lines)}

		elif tab_command == 'new':
			url = params.get('url', 'about:blank')
			target_id = await bs._cdp_create_new_page(url, background=True)
			bs.agent_focus_target_id = target_id
			return {'created': target_id[:8], 'url': url}

		elif tab_command == 'switch':
			tab_index = params['tab']
			page_targets = bs.session_manager.get_all_page_targets() if bs.session_manager else []
			if tab_index < 0 or tab_index >= len(page_targets):
				return {'error': f'Invalid tab index {tab_index}. Available: 0-{len(page_targets) - 1}'}
			bs.agent_focus_target_id = page_targets[tab_index].target_id
			return {'switched': tab_index}

		elif tab_command == 'close':
			tab_indices = params.get('tabs', [])

			page_targets = bs.session_manager.get_all_page_targets() if bs.session_manager else []

			async def _close_target(tid: str) -> None:
				cdp_session = await bs.get_or_create_cdp_session(target_id=None, focus=False)
				if cdp_session:
					await cdp_session.cdp_client.send.Target.closeTarget(params={'targetId': tid})

			if not tab_indices:
				# Use caller's logical focus, not Chrome's global focus
				target_id = bs.agent_focus_target_id
				if not target_id:
					target_id = bs.session_manager.get_focused_target().target_id if bs.session_manager else None
				if not target_id:
					return {'error': 'No focused tab to close'}
				await _close_target(target_id)
				return {'closed': [0]}

			closed = []
			errors = []
			for idx in sorted(tab_indices, reverse=True):
				if idx < 0 or idx >= len(page_targets):
					errors.append(f'Tab {idx} out of range')
					continue
				try:
					await _close_target(page_targets[idx].target_id)
					closed.append(idx)
				except Exception as e:
					errors.append(f'Tab {idx}: {e}')
			result: dict[str, Any] = {'closed': closed}
			if errors:
				result['errors'] = errors
			return result

		return {'error': 'Invalid tab command. Use: list, new, switch, close'}

	elif action == 'keys':
		keys = params['keys']
		await actions.send_keys(keys)
		return {'sent': keys}

	elif action == 'select':
		index = params['index']
		value = params['value']
		node = await bs.get_element_by_index(index)
		if node is None:
			return {'error': f'Element index {index} not found - page may have changed'}
		await actions.select_dropdown(node, value)
		return {'selected': value, 'element': index}

	elif action == 'upload':
		index = params['index']
		file_path = params['path']

		p = Path(file_path)
		if not p.exists():
			return {'error': f'File not found: {file_path}'}
		if not p.is_file():
			return {'error': f'Not a file: {file_path}'}
		if p.stat().st_size == 0:
			return {'error': f'File is empty (0 bytes): {file_path}'}

		node = await bs.get_element_by_index(index)
		if node is None:
			return {'error': f'Element index {index} not found - page may have changed'}

		file_input_node = bs.find_file_input_near_element(node)

		if file_input_node is None:
			selector_map = await bs.get_selector_map()
			file_input_indices = [idx for idx, el in selector_map.items() if bs.is_file_input(el)]
			if file_input_indices:
				hint = f' File input(s) found at index: {", ".join(map(str, file_input_indices))}'
			else:
				hint = ' No file input found on the page.'
			return {'error': f'Element {index} is not a file input.{hint}'}

		await actions.upload_file(file_input_node, file_path)
		return {'uploaded': file_path, 'element': index}

	elif action == 'eval':
		js = params['js']
		# Execute JavaScript via CDP
		result = await _execute_js(session, js)
		return {'result': result}

	elif action == 'extract':
		query = params['query']
		# This requires LLM integration
		# For now, return a placeholder
		return {'query': query, 'error': 'extract is not yet implemented'}

	elif action == 'hover':
		index = params['index']
		node = await bs.get_element_by_index(index)
		if node is None:
			return {'error': f'Element index {index} not found - page may have changed'}

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
			# Use the node's text from our model
			text = node.get_all_children_text(max_depth=10) if node else ''
			return {'index': index, 'text': text}

		elif get_command == 'value':
			index = params['index']
			node = await bs.get_element_by_index(index)
			if node is None:
				return {'error': f'Element index {index} not found - page may have changed'}

			try:
				cdp_session = await bs.cdp_client_for_node(node)
				resolve_result = await cdp_session.cdp_client.send.DOM.resolveNode(
					params={'backendNodeId': node.backend_node_id},
					session_id=cdp_session.session_id,
				)
				object_id = resolve_result['object'].get('objectId')  # type: ignore[union-attr]

				if object_id:
					value_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
						params={
							'objectId': object_id,
							'functionDeclaration': 'function() { return this.value; }',
							'returnByValue': True,
						},
						session_id=cdp_session.session_id,
					)
					value = value_result.get('result', {}).get('value')
					return {'index': index, 'value': value or ''}
				else:
					return {'index': index, 'value': ''}
			except Exception as e:
				logger.error(f'Failed to get element value: {e}')
				return {'index': index, 'value': ''}

		elif get_command == 'attributes':
			index = params['index']
			node = await bs.get_element_by_index(index)
			if node is None:
				return {'error': f'Element index {index} not found - page may have changed'}
			# Use the attributes from the node model
			attrs = node.attributes or {}
			return {'index': index, 'attributes': dict(attrs)}

		elif get_command == 'bbox':
			index = params['index']
			node = await bs.get_element_by_index(index)
			if node is None:
				return {'error': f'Element index {index} not found - page may have changed'}

			try:
				cdp_session = await bs.cdp_client_for_node(node)
				box_result = await cdp_session.cdp_client.send.DOM.getBoxModel(
					params={'backendNodeId': node.backend_node_id},
					session_id=cdp_session.session_id,
				)

				model = box_result['model']  # type: ignore[index]
				content = model.get('content', [])  # type: ignore[union-attr]

				if len(content) >= 8:
					# content is [x1, y1, x2, y2, x3, y3, x4, y4] - corners of the quad
					x = min(content[0], content[2], content[4], content[6])
					y = min(content[1], content[3], content[5], content[7])
					width = max(content[0], content[2], content[4], content[6]) - x
					height = max(content[1], content[3], content[5], content[7]) - y
					return {'index': index, 'bbox': {'x': x, 'y': y, 'width': width, 'height': height}}
				else:
					return {'index': index, 'bbox': {}}
			except Exception as e:
				logger.error(f'Failed to get element bbox: {e}')
				return {'index': index, 'bbox': {}}

		return {'error': 'Invalid get command. Use: title, html, text, value, attributes, bbox'}

	elif action == 'record':
		# CLIBrowserSession skips watchdogs by default — attach RecordingWatchdog lazily on first use.
		watchdog = getattr(bs, '_recording_watchdog', None)
		if watchdog is None:
			from browser_use.browser.watchdogs.recording_watchdog import RecordingWatchdog

			RecordingWatchdog.model_rebuild()
			watchdog = RecordingWatchdog(event_bus=bs.event_bus, browser_session=bs)
			watchdog.attach_to_session()
			bs._recording_watchdog = watchdog

		record_command = params.get('record_command')

		if record_command == 'start':
			path = params.get('path')
			if not path:
				return {'error': 'Usage: record start <output-path>'}
			if watchdog.is_recording:
				return {'error': 'Recording already in progress. Call `record stop` first.'}

			output_path = Path(path).expanduser()
			try:
				output_path.parent.mkdir(parents=True, exist_ok=True)
			except OSError as e:
				return {'error': f'Cannot create output directory {output_path.parent}: {e}'}

			framerate = params.get('framerate')
			try:
				saved = await watchdog.start_recording(output_path, framerate=framerate)
			except RuntimeError as e:
				return {'error': str(e)}
			return {'recording': True, 'path': str(saved)}

		elif record_command == 'stop':
			if not watchdog.is_recording:
				return {'error': 'No recording in progress'}
			saved = await watchdog.stop_recording()
			if saved is None:
				return {'error': 'No recording in progress'}
			return {'_raw_text': str(saved)}

		elif record_command == 'status':
			recorder = watchdog._recorder
			if recorder is None:
				return {'recording': False}
			return {
				'recording': True,
				'path': str(recorder.output_path),
				'framerate': recorder.framerate,
				'size': {'width': recorder.size['width'], 'height': recorder.size['height']},
			}

		return {'error': 'Invalid record command. Use: start <path>, stop, status'}

	raise ValueError(f'Unknown browser action: {action}')
