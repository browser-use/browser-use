"""Serverless CLI for browser-use - runs commands directly without a session server.

Each command reconnects to the browser via CDP WebSocket URL saved to a state file.
The browser process stays alive between commands; only the Python process exits.

Two-tier reconnection:
  Tier 1 (Lightweight CDP, ~200ms): Most commands use raw CDPClient + Target.attachToTarget.
    No BrowserSession, no watchdogs, no event bus.
  Tier 2 (Full BrowserSession, ~3s): Only for `state` (needs DOMWatchdog) and first-time
    `open` (needs to launch browser).

Usage:
    python -m browser_use.skill_cli.direct open https://example.com
    python -m browser_use.skill_cli.direct state
    python -m browser_use.skill_cli.direct click 200 400
    python -m browser_use.skill_cli.direct screenshot ./shot.png
    python -m browser_use.skill_cli.direct close
"""

import asyncio
import base64
import json
import sys
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from cdp_use import CDPClient

	from browser_use.browser.session import BrowserSession

STATE_FILE = Path(tempfile.gettempdir()) / 'browser-use-direct.json'

# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


def _load_state() -> dict[str, Any]:
	if STATE_FILE.exists():
		try:
			return json.loads(STATE_FILE.read_text())
		except (json.JSONDecodeError, OSError):
			pass
	return {}


def _save_state(state: dict[str, Any]) -> None:
	STATE_FILE.write_text(json.dumps(state))


def _clear_state() -> None:
	STATE_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Selector map cache (persisted in state file under "selector_map" key)
# ---------------------------------------------------------------------------


def _save_selector_cache(selector_map: dict[int, Any]) -> None:
	"""Cache element positions from the selector map into the state file.

	Stores absolute_position (document coordinates) so click-by-index can
	convert to viewport coords at click time using current scroll offset.
	"""
	cache: dict[str, dict[str, Any]] = {}
	for idx, node in selector_map.items():
		pos = getattr(node, 'absolute_position', None)
		if pos is None:
			continue
		text = ''
		if hasattr(node, 'ax_node') and node.ax_node and node.ax_node.name:
			text = node.ax_node.name
		elif hasattr(node, 'node_value') and node.node_value:
			text = node.node_value
		tag = getattr(node, 'node_name', '') or ''
		cache[str(idx)] = {
			'x': pos.x,
			'y': pos.y,
			'w': pos.width,
			'h': pos.height,
			'tag': tag.lower(),
			'text': text[:80],
		}
	state = _load_state()
	state['selector_map'] = cache
	_save_state(state)


def _load_selector_cache() -> dict[int, dict[str, Any]]:
	"""Load cached element positions. Returns {index: {x, y, w, h, tag, text}}."""
	state = _load_state()
	raw = state.get('selector_map', {})
	return {int(k): v for k, v in raw.items()}


# ---------------------------------------------------------------------------
# Tier 1: Lightweight CDP connection (~200ms)
# ---------------------------------------------------------------------------


@dataclass
class LightCDP:
	"""Minimal CDP connection — no BrowserSession, no watchdogs."""

	client: 'CDPClient'
	session_id: str
	target_id: str


@asynccontextmanager
async def _lightweight_cdp():
	"""Connect to the browser via raw CDP. ~200ms total.

	Raises RuntimeError if no saved state or browser is dead.
	"""
	from cdp_use import CDPClient

	state = _load_state()
	cdp_url = state.get('cdp_url')
	if not cdp_url:
		raise RuntimeError('No active browser session')

	client = CDPClient(cdp_url)
	try:
		await client.start()
	except Exception as e:
		raise RuntimeError(f'Cannot connect to browser at {cdp_url}: {e}') from e

	target_id = state.get('target_id')

	# If no saved target, discover one
	if not target_id:
		targets = await client.send.Target.getTargets()
		for t in targets.get('targetInfos', []):
			if t.get('type') == 'page' and t.get('url', '').startswith(('http://', 'https://')):
				target_id = t['targetId']
				break
		if not target_id:
			await client.stop()
			raise RuntimeError('No page target found in browser')

	# Attach to the target
	attach_result = await client.send.Target.attachToTarget(params={'targetId': target_id, 'flatten': True})
	session_id = attach_result.get('sessionId')
	if not session_id:
		await client.stop()
		raise RuntimeError(f'Failed to attach to target {target_id}')

	# Enable required domains
	await client.send.Page.enable(session_id=session_id)
	await client.send.Runtime.enable(session_id=session_id)

	try:
		yield LightCDP(client=client, session_id=session_id, target_id=target_id)
	finally:
		try:
			await client.stop()
		except Exception:
			pass


# ---------------------------------------------------------------------------
# Tier 2: Full BrowserSession (for state + first-time open)
# ---------------------------------------------------------------------------


async def _activate_content_target(session: 'BrowserSession', saved_target_id: str | None) -> None:
	"""After reconnection, ensure the session focuses on the actual page, not about:blank."""
	current_url = await session.get_current_page_url()
	if current_url and current_url.startswith(('http://', 'https://')):
		return

	if saved_target_id and session.session_manager:
		target = session.session_manager.get_target(saved_target_id)
		if target and target.url and target.url.startswith(('http://', 'https://')):
			try:
				await session.get_or_create_cdp_session(saved_target_id, focus=True)
				return
			except (ValueError, Exception):
				pass

	if session._cdp_client_root:
		targets_result = await session._cdp_client_root.send.Target.getTargets()
		for t in targets_result.get('targetInfos', []):
			if t.get('type') == 'page' and t.get('url', '').startswith(('http://', 'https://')):
				try:
					await session.get_or_create_cdp_session(t['targetId'], focus=True)
					return
				except (ValueError, Exception):
					pass


@asynccontextmanager
async def browser(use_remote: bool = False):
	"""Connect to existing browser or launch a new one. Disconnects CDP on exit."""
	from browser_use.browser.session import BrowserSession

	state = _load_state()
	cdp_url = state.get('cdp_url')
	session = None

	if cdp_url:
		session = BrowserSession(cdp_url=cdp_url)
		try:
			await session.start()
			await _activate_content_target(session, state.get('target_id'))
		except Exception:
			_clear_state()
			session = None

	if session is None:
		if use_remote:
			session = BrowserSession(use_cloud=True)
		else:
			session = BrowserSession(headless=False)
		await session.start()
		assert session.cdp_url is not None
		_save_state({'cdp_url': session.cdp_url, 'remote': use_remote})

	try:
		yield session
	finally:
		if session.agent_focus_target_id:
			current_state = _load_state()
			current_state['target_id'] = session.agent_focus_target_id
			_save_state(current_state)
		if session._cdp_client_root:
			try:
				await session._cdp_client_root.stop()
			except Exception:
				pass
		await session.event_bus.stop(clear=True, timeout=2)


# ---------------------------------------------------------------------------
# Lightweight CDP command functions (Tier 1)
# ---------------------------------------------------------------------------


async def _cdp_navigate(cdp: LightCDP, url: str) -> None:
	"""Navigate to URL and invalidate selector cache."""
	await cdp.client.send.Page.navigate(params={'url': url}, session_id=cdp.session_id)
	# Invalidate selector cache — page changed, elements are gone
	state = _load_state()
	state.pop('selector_map', None)
	_save_state(state)


async def _cdp_screenshot(cdp: LightCDP, path: str | None) -> None:
	"""Take screenshot, save to file or print base64+dimensions."""
	result = await cdp.client.send.Page.captureScreenshot(params={'format': 'png'}, session_id=cdp.session_id)
	data = base64.b64decode(result['data'])

	if path:
		p = Path(path)
		p.write_bytes(data)  # noqa: ASYNC240
		print(f'Screenshot saved to {p} ({len(data)} bytes)')
	else:
		# Get viewport dimensions
		metrics = await cdp.client.send.Page.getLayoutMetrics(session_id=cdp.session_id)
		visual = metrics.get('visualViewport', {})
		output: dict[str, Any] = {
			'screenshot': result['data'],
			'size_bytes': len(data),
		}
		if visual:
			output['viewport'] = {
				'width': int(visual.get('clientWidth', 0)),
				'height': int(visual.get('clientHeight', 0)),
			}
		print(json.dumps(output))


async def _cdp_click_coordinate(cdp: LightCDP, x: int, y: int) -> None:
	"""Click at viewport coordinates using CDP Input.dispatchMouseEvent."""
	sid = cdp.session_id
	await cdp.client.send.Input.dispatchMouseEvent(
		params={'type': 'mouseMoved', 'x': x, 'y': y},
		session_id=sid,
	)
	await asyncio.sleep(0.05)
	await cdp.client.send.Input.dispatchMouseEvent(
		params={'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1},
		session_id=sid,
	)
	await asyncio.sleep(0.05)
	await cdp.client.send.Input.dispatchMouseEvent(
		params={'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1},
		session_id=sid,
	)


async def _get_scroll_offset(cdp: LightCDP) -> tuple[float, float]:
	"""Get current scroll position via JS."""
	result = await cdp.client.send.Runtime.evaluate(
		params={
			'expression': 'JSON.stringify({x:window.scrollX,y:window.scrollY})',
			'returnByValue': True,
		},
		session_id=cdp.session_id,
	)
	data = json.loads(result.get('result', {}).get('value', '{"x":0,"y":0}'))
	return (data['x'], data['y'])


async def _cdp_click_index(cdp: LightCDP, index: int) -> None:
	"""Click element by cached index. Converts document coords to viewport coords."""
	cache = _load_selector_cache()
	if index not in cache:
		print(f'Error: Element index {index} not in cache. Run "state" first.', file=sys.stderr)
		sys.exit(1)

	elem = cache[index]
	scroll_x, scroll_y = await _get_scroll_offset(cdp)

	# Center of element in document coords, converted to viewport coords
	viewport_x = int(elem['x'] + elem['w'] / 2 - scroll_x)
	viewport_y = int(elem['y'] + elem['h'] / 2 - scroll_y)

	await _cdp_click_coordinate(cdp, viewport_x, viewport_y)
	tag = elem.get('tag', '')
	text = elem.get('text', '')
	label = f'{tag}' + (f' "{text}"' if text else '')
	print(f'Clicked element [{index}] {label} at ({viewport_x}, {viewport_y})')


async def _cdp_type(cdp: LightCDP, text: str) -> None:
	"""Type text into focused element."""
	await cdp.client.send.Input.insertText(params={'text': text}, session_id=cdp.session_id)


async def _cdp_input(cdp: LightCDP, index: int, text: str) -> None:
	"""Click element by index then type text."""
	await _cdp_click_index(cdp, index)
	await asyncio.sleep(0.1)
	await _cdp_type(cdp, text)
	print(f'Typed "{text}" into element [{index}]')


async def _cdp_scroll(cdp: LightCDP, direction: str) -> None:
	"""Scroll page up or down by 500px."""
	amount = -500 if direction == 'up' else 500
	await cdp.client.send.Runtime.evaluate(
		params={
			'expression': f'window.scrollBy(0, {amount})',
			'returnByValue': True,
		},
		session_id=cdp.session_id,
	)


async def _cdp_back(cdp: LightCDP) -> None:
	"""Go back in browser history."""
	nav = await cdp.client.send.Page.getNavigationHistory(session_id=cdp.session_id)
	current_index = nav.get('currentIndex', 0)
	entries = nav.get('entries', [])
	if current_index > 0:
		prev_entry = entries[current_index - 1]
		await cdp.client.send.Page.navigateToHistoryEntry(params={'entryId': prev_entry['id']}, session_id=cdp.session_id)
		# Invalidate selector cache on navigation
		state = _load_state()
		state.pop('selector_map', None)
		_save_state(state)
	else:
		print('Already at the beginning of history', file=sys.stderr)


async def _cdp_keys(cdp: LightCDP, keys_str: str) -> None:
	"""Send keyboard keys/shortcuts via CDP."""
	from browser_use.actor.utils import get_key_info

	# Key alias normalization (same as default_action_watchdog)
	key_aliases = {
		'ctrl': 'Control',
		'control': 'Control',
		'alt': 'Alt',
		'option': 'Alt',
		'meta': 'Meta',
		'cmd': 'Meta',
		'command': 'Meta',
		'shift': 'Shift',
		'enter': 'Enter',
		'return': 'Enter',
		'tab': 'Tab',
		'delete': 'Delete',
		'backspace': 'Backspace',
		'escape': 'Escape',
		'esc': 'Escape',
		'space': ' ',
		'up': 'ArrowUp',
		'down': 'ArrowDown',
		'left': 'ArrowLeft',
		'right': 'ArrowRight',
		'pageup': 'PageUp',
		'pagedown': 'PageDown',
		'home': 'Home',
		'end': 'End',
	}

	sid = cdp.session_id

	async def dispatch_key(event_type: str, key: str, modifiers: int = 0) -> None:
		from cdp_use.cdp.input.commands import DispatchKeyEventParameters

		code, vk_code = get_key_info(key)
		params: DispatchKeyEventParameters = {'type': event_type, 'key': key, 'code': code}
		if modifiers:
			params['modifiers'] = modifiers
		if vk_code is not None:
			params['windowsVirtualKeyCode'] = vk_code
		await cdp.client.send.Input.dispatchKeyEvent(params=params, session_id=sid)

	# Normalize
	if '+' in keys_str:
		parts = [key_aliases.get(p.strip().lower(), p.strip()) for p in keys_str.split('+')]
		modifiers_list = parts[:-1]
		main_key = parts[-1]

		modifier_map = {'Alt': 1, 'Control': 2, 'Meta': 4, 'Shift': 8}
		modifier_value = 0
		for mod in modifiers_list:
			modifier_value |= modifier_map.get(mod, 0)

		for mod in modifiers_list:
			await dispatch_key('keyDown', mod)
		await dispatch_key('keyDown', main_key, modifier_value)
		await dispatch_key('keyUp', main_key, modifier_value)
		for mod in reversed(modifiers_list):
			await dispatch_key('keyUp', mod)
	else:
		normalized = key_aliases.get(keys_str.strip().lower(), keys_str)
		special_keys = {
			'Enter',
			'Tab',
			'Delete',
			'Backspace',
			'Escape',
			'ArrowUp',
			'ArrowDown',
			'ArrowLeft',
			'ArrowRight',
			'PageUp',
			'PageDown',
			'Home',
			'End',
			'Control',
			'Alt',
			'Meta',
			'Shift',
			'F1',
			'F2',
			'F3',
			'F4',
			'F5',
			'F6',
			'F7',
			'F8',
			'F9',
			'F10',
			'F11',
			'F12',
		}
		if normalized in special_keys:
			await dispatch_key('keyDown', normalized)
			if normalized == 'Enter':
				await cdp.client.send.Input.dispatchKeyEvent(
					params={'type': 'char', 'text': '\r', 'key': 'Enter'},
					session_id=sid,
				)
			await dispatch_key('keyUp', normalized)
		else:
			# Plain text — use insertText for each character
			for char in normalized:
				await cdp.client.send.Input.insertText(
					params={'text': char},
					session_id=sid,
				)


async def _cdp_html(cdp: LightCDP, selector: str | None) -> None:
	"""Get raw HTML of the page or a CSS selector."""
	if selector:
		js = f'(function(){{ const el = document.querySelector({json.dumps(selector)}); return el ? el.outerHTML : null; }})()'
	else:
		js = 'document.documentElement.outerHTML'
	result = await cdp.client.send.Runtime.evaluate(params={'expression': js, 'returnByValue': True}, session_id=cdp.session_id)
	html = result.get('result', {}).get('value')
	if html:
		print(html)
	else:
		msg = f'No element found for selector: {selector}' if selector else 'Error: Could not get HTML'
		print(msg, file=sys.stderr)
		sys.exit(1)


async def _cdp_eval(cdp: LightCDP, js: str) -> None:
	"""Execute JavaScript and print result."""
	result = await cdp.client.send.Runtime.evaluate(params={'expression': js, 'returnByValue': True}, session_id=cdp.session_id)
	value = result.get('result', {}).get('value')
	print(json.dumps(value) if value is not None else 'undefined')


# ---------------------------------------------------------------------------
# Command routing
# ---------------------------------------------------------------------------

# Commands that always use lightweight CDP (Tier 1)
_LIGHTWEIGHT_COMMANDS = frozenset(
	{
		'screenshot',
		'click',
		'type',
		'input',
		'scroll',
		'back',
		'keys',
		'html',
		'eval',
	}
)


async def main() -> int:
	args = sys.argv[1:]
	if not args or args[0] in ('help', '--help', '-h'):
		print("""Usage: python -m browser_use.skill_cli.direct <command> [args]

Commands:
  open <url>              Navigate to URL
  state                   Get DOM state with viewport info
  click <index>           Click element by index (uses cached positions)
  click <x> <y>           Click at viewport coordinates
  type <text>             Type into focused element
  input <index> <text>    Click element then type
  screenshot [path]       Take screenshot (saves to file or prints base64+dimensions)
  scroll [up|down]        Scroll page (default: down)
  back                    Go back in history
  keys <keys>             Send keyboard keys
  html [selector]         Get raw HTML (full page or CSS selector)
  eval <js>               Execute JavaScript
  close                   Kill browser and clean up

Flags:
  --remote                Use browser-use cloud browser (requires BROWSER_USE_API_KEY)""")
		return 0 if args else 1

	# Extract --remote flag
	use_remote = '--remote' in args
	args = [a for a in args if a != '--remote']
	if not args:
		print('Error: No command specified', file=sys.stderr)
		return 1

	command = args[0]

	# ── close: lightweight CDP kill ──────────────────────────────────────
	if command == 'close':
		state = _load_state()
		cdp_url = state.get('cdp_url')
		if not cdp_url:
			print('No active browser session')
		else:
			closed = False
			try:
				from cdp_use import CDPClient

				client = CDPClient(cdp_url)
				await client.start()
				await client.send.Browser.close()
				await client.stop()
				closed = True
			except Exception:
				pass
			if not closed:
				try:
					from browser_use.browser.session import BrowserSession

					session = BrowserSession(cdp_url=cdp_url)
					await session.start()
					await session.kill()
				except Exception:
					pass
		_clear_state()
		print('Browser closed')
		return 0

	# ── open: lightweight if reconnecting, full session if first launch ──
	if command == 'open' and len(args) >= 2:
		url = args[1]
		if not url.startswith(('http://', 'https://', 'file://')):
			url = 'https://' + url

		state = _load_state()
		if state.get('cdp_url'):
			# Reconnect — lightweight CDP navigate
			try:
				async with _lightweight_cdp() as cdp:
					await _cdp_navigate(cdp, url)
					# Update target_id in state
					current_state = _load_state()
					current_state['target_id'] = cdp.target_id
					_save_state(current_state)
					print(f'Navigated to: {url}')
					return 0
			except RuntimeError:
				# Browser died — fall through to full session launch
				_clear_state()

		# First launch — needs full session
		async with browser(use_remote=use_remote) as session:
			from browser_use.browser.events import NavigateToUrlEvent

			await session.event_bus.dispatch(NavigateToUrlEvent(url=url))
			if session.agent_focus_target_id:
				current_state = _load_state()
				current_state['target_id'] = session.agent_focus_target_id
				_save_state(current_state)
			print(f'Navigated to: {url}')
		return 0

	# ── state: full session (needs DOMWatchdog for DOM tree building) ────
	if command == 'state':
		async with browser(use_remote=use_remote) as session:
			state_summary = await session.get_browser_state_summary()
			assert state_summary.dom_state is not None
			text = state_summary.dom_state.llm_representation()
			if state_summary.page_info:
				pi = state_summary.page_info
				header = f'viewport: {pi.viewport_width}x{pi.viewport_height}\n'
				header += f'page: {pi.page_width}x{pi.page_height}\n'
				header += f'scroll: ({pi.scroll_x}, {pi.scroll_y})\n'
				text = header + text
			print(text)

			# Cache selector map for subsequent click-by-index
			selector_map = await session.get_selector_map()
			if selector_map:
				_save_selector_cache(selector_map)
		return 0

	# ── Lightweight commands (Tier 1) ────────────────────────────────────
	if command in _LIGHTWEIGHT_COMMANDS:
		try:
			async with _lightweight_cdp() as cdp:
				if command == 'screenshot':
					path = args[1] if len(args) >= 2 else None
					await _cdp_screenshot(cdp, path)

				elif command == 'click' and len(args) >= 2:
					int_args = [int(a) for a in args[1:]]
					if len(int_args) == 2:
						x, y = int_args
						await _cdp_click_coordinate(cdp, x, y)
						print(f'Clicked at ({x}, {y})')
					elif len(int_args) == 1:
						await _cdp_click_index(cdp, int_args[0])
					else:
						print('Usage: click <index> or click <x> <y>', file=sys.stderr)
						return 1

				elif command == 'type' and len(args) >= 2:
					text = ' '.join(args[1:])
					await _cdp_type(cdp, text)
					print(f'Typed: {text}')

				elif command == 'input' and len(args) >= 3:
					index = int(args[1])
					text = ' '.join(args[2:])
					await _cdp_input(cdp, index, text)

				elif command == 'scroll':
					direction = args[1] if len(args) >= 2 else 'down'
					await _cdp_scroll(cdp, direction)
					print(f'Scrolled {direction}')

				elif command == 'back':
					await _cdp_back(cdp)
					print('Navigated back')

				elif command == 'keys' and len(args) >= 2:
					await _cdp_keys(cdp, ' '.join(args[1:]))
					print(f'Sent keys: {" ".join(args[1:])}')

				elif command == 'html':
					selector = args[1] if len(args) >= 2 else None
					await _cdp_html(cdp, selector)

				elif command == 'eval' and len(args) >= 2:
					js = ' '.join(args[1:])
					await _cdp_eval(cdp, js)

				else:
					print(f'Missing arguments for: {command}', file=sys.stderr)
					return 1

		except RuntimeError as e:
			print(f'Error: {e}', file=sys.stderr)
			return 1
		return 0

	print(f'Unknown command: {command}', file=sys.stderr)
	return 1


if __name__ == '__main__':
	sys.exit(asyncio.run(main()))
