"""Safari real-profile backend for Browser Use."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from browser_use.browser.backends.base import BackendCapabilityReport, BrowserBackend
from browser_use.browser.views import BrowserError, BrowserStateSummary, PageInfo, TabInfo
from browser_use.dom.views import (
	DOMRect,
	EnhancedDOMTreeNode,
	EnhancedSnapshotNode,
	NodeType,
	SerializedDOMState,
	SimplifiedNode,
)

SAFARI_APP_PATH = '/Applications/Safari.app'
MINIMUM_SAFARI_VERSION = '26.3.1'
MINIMUM_MACOS_VERSION = '26.0'
PROFILE_TITLE_SEPARATOR = ' — '
SCREENSHOT_TIMEOUT_SECONDS = 10.0


def _safe_process_output(value: str | bytes | None) -> str:
	"""Normalize subprocess output for BrowserError details."""
	if value is None:
		return ''
	if isinstance(value, bytes):
		return value.decode('utf-8', errors='replace').strip()
	return value.strip()


def _run_jxa_sync(script: str, timeout: float = 15) -> str:
	try:
		result = subprocess.run(
			['osascript', '-l', 'JavaScript'],
			input=script,
			capture_output=True,
			text=True,
			check=True,
			timeout=timeout,
		)
		return result.stdout.strip()
	except subprocess.TimeoutExpired as exc:
		raise BrowserError(
			'Safari automation command timed out.',
			details={
				'timeout_seconds': timeout,
				'stderr': _safe_process_output(exc.stderr),
				'stdout': _safe_process_output(exc.stdout),
			},
		) from exc
	except subprocess.CalledProcessError as exc:
		raise BrowserError(
			'Safari automation command failed.',
			details={'stderr': _safe_process_output(exc.stderr), 'stdout': _safe_process_output(exc.stdout)},
		) from exc
	except OSError as exc:
		raise BrowserError(
			'Safari automation command could not be launched.',
			details={'error': str(exc)},
		) from exc


def _read_safari_version() -> str:
	try:
		result = subprocess.run(
			['defaults', 'read', f'{SAFARI_APP_PATH}/Contents/Info', 'CFBundleShortVersionString'],
			check=True,
			capture_output=True,
			text=True,
			timeout=2,
		)
		return result.stdout.strip()
	except Exception:
		return '0.0.0'


def _read_macos_version() -> str:
	try:
		result = subprocess.run(['sw_vers', '-productVersion'], check=True, capture_output=True, text=True, timeout=2)
		return result.stdout.strip()
	except Exception:
		return '0.0'


def _version_at_least(version: str, minimum: str) -> bool:
	def parse(raw: str) -> tuple[int, ...]:
		return tuple(int(piece) for piece in raw.split('.') if piece.isdigit())

	current = parse(version)
	required = parse(minimum)
	width = max(len(current), len(required))
	return current + (0,) * (width - len(current)) >= required + (0,) * (width - len(required))


def _probe_gui_scripting_sync() -> bool:
	try:
		_run_jxa_sync(
			"""
			const safari = Application("Safari");
			safari.activate();
			const se = Application("System Events");
			const proc = se.processes.byName("Safari");
			JSON.stringify(proc.menuBars[0].menuBarItems.name());
			""",
			timeout=5,
		)
		return True
	except Exception:
		return False


def probe_local_safari_backend(profile: str = 'active') -> BackendCapabilityReport:
	"""Probe the requirements for the local Safari real-profile backend."""
	details = {
		'macos_version': _read_macos_version(),
		'safari_version': _read_safari_version(),
		'gui_scripting_available': _probe_gui_scripting_sync(),
		'screen_capture_available': shutil_which('screencapture') is not None,
		'profile': profile,
	}
	if os.uname().sysname != 'Darwin':
		return BackendCapabilityReport(
			backend='safari',
			available=False,
			reason='Safari backend is only supported on macOS 26+ with Safari 26.3.1 or newer.',
			details=details,
		)
	if not Path(SAFARI_APP_PATH).exists():
		return BackendCapabilityReport(
			backend='safari',
			available=False,
			reason='Safari.app was not found in /Applications.',
			details=details,
		)
	if not _version_at_least(str(details['macos_version']), MINIMUM_MACOS_VERSION):
		return BackendCapabilityReport(
			backend='safari',
			available=False,
			reason=f'macOS {details["macos_version"]} is too old for Safari real-profile support. Require {MINIMUM_MACOS_VERSION}+.',
			details=details,
		)
	if not _version_at_least(str(details['safari_version']), MINIMUM_SAFARI_VERSION):
		return BackendCapabilityReport(
			backend='safari',
			available=False,
			reason=f'Safari {details["safari_version"]} is too old. Require {MINIMUM_SAFARI_VERSION}+.',
			details=details,
		)
	return BackendCapabilityReport(backend='safari', available=True, details=details)


class SafariRealProfileBackend(BrowserBackend):
	"""Backend that drives the user’s real Safari profile windows via JXA."""

	name = 'safari'

	def __init__(self, browser_session) -> None:
		super().__init__(browser_session)
		self._selector_map: dict[int, EnhancedDOMTreeNode] = {}

	async def start(self) -> BackendCapabilityReport:
		report = await self._probe_capabilities()
		if not report.available:
			raise BrowserError(report.reason or 'Safari backend is unavailable', details=report.details)

		await self._ensure_profile_window()
		tabs = await self.get_tabs()
		if tabs:
			self.browser_session.agent_focus_target_id = tabs[0].target_id
		self.logger.info(
			f'🧭 Safari backend attached to profile={self.browser_session.browser_profile.safari_profile!r} '
			f'(Safari {report.details.get("safari_version")}, macOS {report.details.get("macos_version")})'
		)
		return report

	async def stop(self, force: bool = False) -> None:
		# Intentionally do not close Safari windows. This backend attaches to the user's real profile.
		return None

	async def get_tabs(self) -> list[TabInfo]:
		window = await self._ensure_profile_window()
		payload = await self._run_jxa_json(
			f"""
			const safari = Application("Safari");
			safari.activate();
			const windowId = {window['windowId']};
			const win = safari.windows().find(w => w.id() === windowId) || safari.windows()[0];
			const currentIndex = win.currentTab().index();
			const tabs = win.tabs().map(tab => ({{
				windowId: win.id(),
				tabIndex: tab.index(),
				url: tab.url() || "about:blank",
				title: tab.name() || "",
				isCurrent: tab.index() === currentIndex,
			}}));
			JSON.stringify(tabs);
			"""
		)
		tabs: list[TabInfo] = []
		for tab in payload:
			target_id = self._target_id(int(tab['windowId']), int(tab['tabIndex']))
			tabs.append(
				TabInfo(
					target_id=target_id,
					url=str(tab.get('url') or 'about:blank'),
					title=str(tab.get('title') or ''),
					parent_target_id=None,
				)
			)
			if tab.get('isCurrent'):
				self.browser_session.agent_focus_target_id = target_id
		return tabs

	async def get_current_page_url(self) -> str:
		window = await self._ensure_profile_window()
		return str(window.get('url') or 'about:blank')

	async def get_current_page_title(self) -> str:
		window = await self._ensure_profile_window()
		return str(window.get('title') or '')

	async def navigate_to(self, url: str, new_tab: bool = False) -> None:
		await self._ensure_profile_window()
		await self._run_jxa(
			f"""
			const safari = Application("Safari");
			safari.activate();
			const url = {json.dumps(url)};
			if (safari.windows.length === 0) {{
				safari.Document().make();
			}}
			const win = safari.windows()[0];
			if ({'true' if new_tab else 'false'}) {{
				safari.Tab({{url}}).make();
				const tabs = win.tabs();
				win.currentTab = tabs[tabs.length - 1];
			}} else {{
				win.currentTab().url = url;
			}}
			"""
		)
		await asyncio.sleep(0.35)
		await self._refresh_focus_target()

	async def evaluate_javascript(self, expression: str) -> Any:
		await self._ensure_profile_window()
		output = await self._run_jxa(
			f"""
			const safari = Application("Safari");
			safari.activate();
			if (safari.windows.length === 0) {{
				throw new Error("Safari has no open windows.");
			}}
			const result = safari.doJavaScript({json.dumps(expression)}, {{ in: safari.windows()[0].currentTab() }});
			if (result === undefined || result === null) {{
				JSON.stringify({{type: "null", value: null}});
			}} else if (typeof result === "string") {{
				try {{
					const parsed = JSON.parse(result);
					JSON.stringify({{type: "json", value: parsed}});
				}} catch (error) {{
					JSON.stringify({{type: "string", value: result}});
				}}
			}} else {{
				JSON.stringify({{type: typeof result, value: result}});
			}}
			"""
		)
		payload = json.loads(output)
		return payload.get('value')

	async def take_screenshot(
		self,
		path: str | None = None,
		full_page: bool = False,
		format: str = 'png',
		quality: int | None = None,
		clip: dict[str, Any] | None = None,
	) -> bytes:
		window = await self._ensure_profile_window()
		window_id = int(window['windowId'])
		if full_page:
			self.logger.debug('Safari backend ignores full_page screenshots and captures the active window instead.')
		if clip:
			self.logger.debug('Safari backend ignores clip screenshots and captures the active window instead.')
		if format != 'png':
			self.logger.debug(f'Safari backend captures PNG screenshots only; ignoring requested format={format!r}')
		if quality is not None:
			self.logger.debug('Safari backend ignores JPEG quality because screenshots are captured as PNG.')

		if path:
			output_path = Path(path)
		else:
			fd, temp_path = tempfile.mkstemp(prefix='browser-use-safari-', suffix='.png')
			os.close(fd)
			output_path = Path(temp_path)
		try:
			await asyncio.to_thread(
				subprocess.run,
				['screencapture', '-l', str(window_id), str(output_path)],
				check=True,
				capture_output=True,
				text=True,
				timeout=SCREENSHOT_TIMEOUT_SECONDS,
			)
			return output_path.read_bytes()
		except subprocess.CalledProcessError as exc:
			raise BrowserError(
				'Safari screenshot capture failed. Grant Screen Recording permission to the terminal/app and retry.',
				details={'stderr': exc.stderr.strip()},
			) from exc
		finally:
			if not path:
				output_path.unlink(missing_ok=True)

	async def get_browser_state_summary(
		self,
		include_screenshot: bool = True,
		include_recent_events: bool = False,
	) -> BrowserStateSummary:
		window = await self._ensure_profile_window()
		state = await self.evaluate_javascript(self._state_extraction_script())
		if not isinstance(state, dict):
			raise BrowserError('Safari state extraction returned an unexpected payload', details={'payload': state})

		current_target_id = self._target_id(int(window['windowId']), int(window['currentTabIndex']))
		self.browser_session.agent_focus_target_id = current_target_id
		dom_state = self._build_serialized_dom_state(state, current_target_id)
		self.browser_session.update_cached_selector_map(dom_state.selector_map)
		self._selector_map = dom_state.selector_map

		screenshot_b64: str | None = None
		if include_screenshot:
			try:
				screenshot_b64 = base64.b64encode(await self.take_screenshot()).decode('utf-8')
			except BrowserError as exc:
				self.logger.warning(f'Safari screenshot unavailable: {exc}')

		page = state.get('page', {})
		page_info = PageInfo(
			viewport_width=int(page.get('viewportWidth') or 0),
			viewport_height=int(page.get('viewportHeight') or 0),
			page_width=int(page.get('pageWidth') or 0),
			page_height=int(page.get('pageHeight') or 0),
			scroll_x=int(page.get('scrollX') or 0),
			scroll_y=int(page.get('scrollY') or 0),
			pixels_above=int(page.get('pixelsAbove') or 0),
			pixels_below=int(page.get('pixelsBelow') or 0),
			pixels_left=0,
			pixels_right=0,
		)

		browser_state = BrowserStateSummary(
			dom_state=dom_state,
			url=str(state.get('url') or window.get('url') or 'about:blank'),
			title=str(state.get('title') or window.get('title') or ''),
			tabs=await self.get_tabs(),
			screenshot=screenshot_b64,
			page_info=page_info,
			pixels_above=page_info.pixels_above,
			pixels_below=page_info.pixels_below,
			recent_events='Safari real-profile backend' if include_recent_events else None,
			closed_popup_messages=list(self.browser_session._closed_popup_messages),
		)
		self.browser_session._cached_browser_state_summary = browser_state
		return browser_state

	async def get_element_by_index(self, index: int) -> EnhancedDOMTreeNode | None:
		return self._selector_map.get(index)

	async def highlight_interaction_element(self, node: EnhancedDOMTreeNode) -> None:
		await self.evaluate_javascript(
			f"""
			(() => {{
				const el = document.querySelector('[data-browser-use-safari-id="{node.backend_node_id}"]');
				if (!el) return false;
				const rect = el.getBoundingClientRect();
				const overlay = document.createElement('div');
				overlay.setAttribute('data-browser-use-safari-highlight', 'true');
				overlay.style.cssText = [
					'position: fixed',
					'left: ' + rect.left + 'px',
					'top: ' + rect.top + 'px',
					'width: ' + rect.width + 'px',
					'height: ' + rect.height + 'px',
					'border: 2px solid {self.browser_session.browser_profile.interaction_highlight_color}',
					'pointer-events: none',
					'z-index: 2147483647',
				].join(';');
				document.body.appendChild(overlay);
				setTimeout(() => overlay.remove(), {int(self.browser_session.browser_profile.interaction_highlight_duration * 1000)});
				return true;
			}})()
			"""
		)

	async def highlight_coordinate_click(self, x: int, y: int) -> None:
		await self.evaluate_javascript(
			f"""
			(() => {{
				const marker = document.createElement('div');
				marker.style.cssText = [
					'position: fixed',
					'left: ' + ({x} - 6) + 'px',
					'top: ' + ({y} - 6) + 'px',
					'width: 12px',
					'height: 12px',
					'border-radius: 999px',
					'background: {json.dumps(self.browser_session.browser_profile.interaction_highlight_color)}',
					'pointer-events: none',
					'z-index: 2147483647',
				].join(';');
				document.body.appendChild(marker);
				setTimeout(() => marker.remove(), {int(self.browser_session.browser_profile.interaction_highlight_duration * 1000)});
				return true;
			}})()
			"""
		)

	async def focus_tab(self, target_id: str | None) -> str:
		await self._ensure_profile_window()
		if target_id is None:
			tabs = await self.get_tabs()
			if not tabs:
				raise BrowserError('Safari has no open tabs to focus.')
			target_id = tabs[-1].target_id

		window_id, tab_index = self._parse_target_id(target_id)
		await self._run_jxa(
			f"""
			const safari = Application("Safari");
			safari.activate();
			const win = safari.windows().find(w => w.id() === {window_id});
			if (!win) throw new Error("Safari window {window_id} not found");
			const tab = win.tabs().find(t => t.index() === {tab_index});
			if (!tab) throw new Error("Safari tab {tab_index} not found");
			win.currentTab = tab;
			"""
		)
		self.browser_session.agent_focus_target_id = target_id
		return target_id

	async def close_tab(self, target_id: str) -> None:
		window_id, tab_index = self._parse_target_id(target_id)
		await self._run_jxa(
			f"""
			const safari = Application("Safari");
			safari.activate();
			const win = safari.windows().find(w => w.id() === {window_id});
			if (!win) return;
			const tab = win.tabs().find(t => t.index() === {tab_index});
			if (!tab) return;
			tab.close();
			"""
		)
		await asyncio.sleep(0.15)
		await self._refresh_focus_target()

	async def click_element(self, node: EnhancedDOMTreeNode, button: str = 'left') -> dict[str, Any] | None:
		await self._ensure_profile_window()
		result = await self.evaluate_javascript(
			f"""
			(() => {{
				const el = document.querySelector('[data-browser-use-safari-id="{node.backend_node_id}"]');
				if (!el) return {{ ok: false, error: 'not_found' }};
				el.scrollIntoView({{ block: 'center', inline: 'center' }});
				if (typeof el.focus === 'function') {{
					el.focus({{ preventScroll: true }});
				}}
				const rect = el.getBoundingClientRect();
				if ({json.dumps(button)} === 'right') {{
					el.dispatchEvent(new MouseEvent('contextmenu', {{ bubbles: true, cancelable: true, button: 2, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 }}));
				}} else {{
					if (typeof el.click === 'function') {{
						el.click();
					}} else {{
						el.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true, button: 0, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 }}));
					}}
				}}
				return {{ ok: true }};
			}})()
			"""
		)
		await asyncio.sleep(0.25)
		await self._refresh_focus_target()
		return result if isinstance(result, dict) else None

	async def hover_element(self, node: EnhancedDOMTreeNode) -> dict[str, Any] | None:
		"""Dispatch hover events for an indexed DOM element."""
		await self._ensure_profile_window()
		result = await self.evaluate_javascript(
			f"""
			(() => {{
				const el = document.querySelector('[data-browser-use-safari-id="{node.backend_node_id}"]');
				if (!el) return {{ ok: false, error: 'not_found' }};
				el.scrollIntoView({{ block: 'center', inline: 'center' }});
				const rect = el.getBoundingClientRect();
				const clientX = rect.left + rect.width / 2;
				const clientY = rect.top + rect.height / 2;
				for (const type of ['pointerover', 'mouseover', 'mouseenter', 'pointermove', 'mousemove']) {{
					el.dispatchEvent(new MouseEvent(type, {{ bubbles: true, cancelable: true, clientX, clientY }}));
				}}
				return {{ ok: true }};
			}})()
			"""
		)
		return result if isinstance(result, dict) else None

	async def double_click_element(self, node: EnhancedDOMTreeNode) -> dict[str, Any] | None:
		"""Dispatch a double-click for an indexed DOM element."""
		await self._ensure_profile_window()
		result = await self.evaluate_javascript(
			f"""
			(() => {{
				const el = document.querySelector('[data-browser-use-safari-id="{node.backend_node_id}"]');
				if (!el) return {{ ok: false, error: 'not_found' }};
				el.scrollIntoView({{ block: 'center', inline: 'center' }});
				if (typeof el.focus === 'function') {{
					el.focus({{ preventScroll: true }});
				}}
				const rect = el.getBoundingClientRect();
				const clientX = rect.left + rect.width / 2;
				const clientY = rect.top + rect.height / 2;
				for (const type of ['mousedown', 'mouseup', 'click', 'mousedown', 'mouseup', 'click', 'dblclick']) {{
					el.dispatchEvent(
						new MouseEvent(type, {{
							bubbles: true,
							cancelable: true,
							button: 0,
							detail: type === 'dblclick' ? 2 : 1,
							clientX,
							clientY,
						}})
					);
				}}
				return {{ ok: true }};
			}})()
			"""
		)
		await asyncio.sleep(0.25)
		await self._refresh_focus_target()
		return result if isinstance(result, dict) else None

	async def click_coordinate(self, x: int, y: int, button: str = 'left') -> dict[str, Any] | None:
		await self._ensure_profile_window()
		result = await self.evaluate_javascript(
			f"""
			(() => {{
				const el = document.elementFromPoint({x}, {y});
				if (!el) return {{ ok: false, error: 'not_found' }};
				if ({json.dumps(button)} === 'right') {{
					el.dispatchEvent(new MouseEvent('contextmenu', {{ bubbles: true, cancelable: true, button: 2, clientX: {x}, clientY: {y} }}));
				}} else if (typeof el.click === 'function') {{
					el.click();
				}} else {{
					el.dispatchEvent(new MouseEvent('click', {{ bubbles: true, cancelable: true, button: 0, clientX: {x}, clientY: {y} }}));
				}}
				return {{ ok: true, tag: el.tagName.toLowerCase() }};
			}})()
			"""
		)
		await asyncio.sleep(0.25)
		await self._refresh_focus_target()
		return result if isinstance(result, dict) else None

	async def type_text(self, node: EnhancedDOMTreeNode, text: str, clear: bool = True) -> dict[str, Any] | None:
		await self._ensure_profile_window()
		result = await self.evaluate_javascript(
			f"""
			(() => {{
				const el = document.querySelector('[data-browser-use-safari-id="{node.backend_node_id}"]');
				if (!el) return {{ ok: false, error: 'not_found' }};
				el.scrollIntoView({{ block: 'center', inline: 'center' }});
				if (typeof el.focus === 'function') {{
					el.focus({{ preventScroll: true }});
				}}
				const value = {json.dumps(text)};
				if ({'true' if clear else 'false'}) {{
					if ('value' in el) el.value = '';
					if (el.isContentEditable) el.textContent = '';
				}}
				if ('value' in el) {{
					el.value = value;
				}} else if (el.isContentEditable) {{
					el.textContent = value;
				}} else {{
					el.setAttribute('value', value);
				}}
				el.dispatchEvent(new Event('input', {{ bubbles: true }}));
				el.dispatchEvent(new Event('change', {{ bubbles: true }}));
				return {{ ok: true }};
			}})()
			"""
		)
		return result if isinstance(result, dict) else None

	async def scroll(self, direction: str, amount: int, node: EnhancedDOMTreeNode | None = None) -> None:
		await self._ensure_profile_window()
		delta_x = amount if direction == 'right' else -amount if direction == 'left' else 0
		delta_y = amount if direction == 'down' else -amount if direction == 'up' else 0
		if node is None:
			await self.evaluate_javascript(f'window.scrollBy({delta_x}, {delta_y}); true;')
			return

		await self.evaluate_javascript(
			f"""
			(() => {{
				const el = document.querySelector('[data-browser-use-safari-id="{node.backend_node_id}"]');
				if (!el) return false;
				el.scrollBy({delta_x}, {delta_y});
				return true;
			}})()
			"""
		)

	async def go_back(self) -> None:
		await self.evaluate_javascript('history.back(); true;')
		await asyncio.sleep(0.25)
		await self._refresh_focus_target()

	async def go_forward(self) -> None:
		await self.evaluate_javascript('history.forward(); true;')
		await asyncio.sleep(0.25)
		await self._refresh_focus_target()

	async def refresh(self) -> None:
		await self.evaluate_javascript('location.reload(); true;')
		await asyncio.sleep(0.35)
		await self._refresh_focus_target()

	async def send_keys(self, keys: str) -> None:
		gui_report = await self._probe_gui_scripting()
		if not gui_report:
			raise BrowserError(
				'Safari send_keys requires Accessibility permission for GUI scripting. '
				'Grant permission to your terminal/app in System Settings > Privacy & Security > Accessibility.'
			)

		await self._ensure_profile_window()
		steps: list[str] = []
		for token in [piece for piece in keys.split() if piece]:
			script = self._build_keystroke_script(token)
			if script is None:
				raise BrowserError(f'Safari send_keys does not support token {token!r} yet.')
			steps.append(script)

		await self._run_jxa(
			f"""
			const currentApp = Application.currentApplication();
			currentApp.includeStandardAdditions = true;
			const safari = Application("Safari");
			safari.activate();
			const se = Application("System Events");
			{''.join(steps)}
			"""
		)

	async def get_dropdown_options(self, node: EnhancedDOMTreeNode) -> dict[str, str]:
		result = await self.evaluate_javascript(
			f"""
			(() => {{
				const el = document.querySelector('[data-browser-use-safari-id="{node.backend_node_id}"]');
				if (!el) return {{}};
				const options = Array.from(el.options || []).map(option => [option.textContent.trim(), option.value]);
				return Object.fromEntries(options);
			}})()
			"""
		)
		return result if isinstance(result, dict) else {}

	async def select_dropdown_option(self, node: EnhancedDOMTreeNode, text: str) -> dict[str, str]:
		result = await self.evaluate_javascript(
			f"""
			(() => {{
				const el = document.querySelector('[data-browser-use-safari-id="{node.backend_node_id}"]');
				if (!el || !el.options) return {{ error: 'not_found' }};
				const options = Array.from(el.options);
				const match = options.find(option => option.textContent.trim() === {json.dumps(text)} || option.value === {json.dumps(text)});
				if (!match) return {{ error: 'option_not_found' }};
				el.value = match.value;
				match.selected = true;
				el.dispatchEvent(new Event('input', {{ bubbles: true }}));
				el.dispatchEvent(new Event('change', {{ bubbles: true }}));
				return {{ text: match.textContent.trim(), value: match.value }};
			}})()
			"""
		)
		return result if isinstance(result, dict) else {}

	async def scroll_to_text(self, text: str, direction: str = 'down') -> None:
		result = await self.evaluate_javascript(
			f"""
			(() => {{
				const query = {json.dumps(text)}.toLowerCase();
				const nodes = Array.from(document.querySelectorAll('body *')).filter(el => {{
					const value = (el.innerText || el.textContent || '').toLowerCase();
					return value.includes(query);
				}});
				if (!nodes.length) return false;
				const node = {'nodes[nodes.length - 1]' if direction == 'up' else 'nodes[0]'};
				node.scrollIntoView({{ block: 'center' }});
				return true;
			}})()
			"""
		)
		if result is not True:
			raise BrowserError(f'Text {text!r} was not found on the current Safari page.')

	async def upload_file(self, node: EnhancedDOMTreeNode, file_path: str) -> None:
		gui_report = await self._probe_gui_scripting()
		if not gui_report:
			raise BrowserError(
				'Safari file upload requires Accessibility permission for GUI scripting. '
				'Grant permission to your terminal/app in System Settings > Privacy & Security > Accessibility.'
			)

		absolute_path = str(Path(file_path).expanduser().resolve())
		await self.click_element(node)
		await asyncio.sleep(0.4)
		await self._run_jxa(
			f"""
			const currentApp = Application.currentApplication();
			currentApp.includeStandardAdditions = true;
			const safari = Application("Safari");
			safari.activate();
			const se = Application("System Events");
			se.keystroke("g", {{ using: ["command down", "shift down"] }});
			currentApp.delay(0.15);
			se.keystroke({json.dumps(absolute_path)});
			currentApp.delay(0.1);
			se.keyCode(36);
			currentApp.delay(0.15);
			se.keyCode(36);
			"""
		)

	async def _probe_capabilities(self) -> BackendCapabilityReport:
		profile = self.browser_session.browser_profile.safari_profile or 'active'
		return await asyncio.to_thread(probe_local_safari_backend, profile)

	async def _probe_gui_scripting(self) -> bool:
		return await asyncio.to_thread(_probe_gui_scripting_sync)

	async def _ensure_profile_window(self) -> dict[str, Any]:
		profile = (self.browser_session.browser_profile.safari_profile or 'active').strip() or 'active'
		await self._run_jxa(
			"""
			const currentApp = Application.currentApplication();
			currentApp.includeStandardAdditions = true;
			const safari = Application("Safari");
			safari.activate();
			if (safari.windows.length === 0) {
				safari.Document().make();
				currentApp.delay(0.2);
			}
			"""
		)

		if profile.lower() != 'active':
			focused = await self._focus_existing_profile_window(profile)
			if not focused:
				await self._open_profile_window(profile)

		window = await self._get_front_window()
		if profile.lower() != 'active':
			window_profile = self._extract_profile_label(str(window.get('windowName') or ''))
			if window_profile != profile:
				raise BrowserError(
					f'Safari could not focus profile {profile!r}. '
					'Open a window in that profile manually, or grant Accessibility permission so Browser Use can select File > '
					f'New {profile} Window.',
					details={'window': window},
				)
		return window

	async def _focus_existing_profile_window(self, profile: str) -> bool:
		result = await self._run_jxa_json(
			f"""
			const safari = Application("Safari");
			safari.activate();
			const profile = {json.dumps(profile)};
			const separator = {json.dumps(PROFILE_TITLE_SEPARATOR)};
			for (const win of safari.windows()) {{
				const title = win.name() || "";
				if (title.startsWith(profile + separator) || title === profile) {{
					win.index = 1;
					JSON.stringify({{ focused: true }});
					break;
				}}
			}}
			JSON.stringify({{ focused: false }});
			"""
		)
		return bool(result.get('focused'))

	async def _open_profile_window(self, profile: str) -> None:
		gui_available = await self._probe_gui_scripting()
		if not gui_available:
			raise BrowserError(
				f'Safari profile {profile!r} is not currently open. '
				f'Open a {profile} Safari window manually, or grant Accessibility permission so Browser Use can open it for you.'
			)

		item_name = f'New {profile} Window'
		result = await self._run_jxa_json(
			f"""
			const currentApp = Application.currentApplication();
			currentApp.includeStandardAdditions = true;
			const safari = Application("Safari");
			safari.activate();
			const se = Application("System Events");
			const proc = se.processes.byName("Safari");
			const fileMenu = proc.menuBars[0].menuBarItems.byName("File").menus[0];
			const itemName = {json.dumps(item_name)};
			const exists = fileMenu.menuItems.name().includes(itemName);
			if (!exists) {{
				JSON.stringify({{ opened: false, reason: "missing_menu_item" }});
			}} else {{
				fileMenu.menuItems.byName(itemName).click();
				currentApp.delay(0.4);
				JSON.stringify({{ opened: true }});
			}}
			"""
		)
		if not result.get('opened'):
			raise BrowserError(
				f'Safari does not expose File > {item_name}. '
				'Make sure that profile exists in Safari and is available in the current Safari 26.3.1+ build.',
				details=result,
			)

	async def _get_front_window(self) -> dict[str, Any]:
		window = await self._run_jxa_json(
			"""
			const safari = Application("Safari");
			safari.activate();
			if (safari.windows.length === 0) {
				JSON.stringify({windowId: 0, windowName: "", currentTabIndex: 1, title: "", url: "about:blank"});
			} else {
				const win = safari.windows()[0];
				const tab = win.currentTab();
				JSON.stringify({
					windowId: win.id(),
					windowName: win.name() || "",
					currentTabIndex: tab.index(),
					title: tab.name() || "",
					url: tab.url() || "about:blank",
				});
			}
			"""
		)
		return window

	async def _refresh_focus_target(self) -> None:
		window = await self._get_front_window()
		self.browser_session.agent_focus_target_id = self._target_id(
			int(window['windowId']),
			int(window['currentTabIndex']),
		)

	def _build_serialized_dom_state(self, state: dict[str, Any], target_id: str) -> SerializedDOMState:
		selector_map: dict[int, EnhancedDOMTreeNode] = {}
		next_node_id = 1

		def make_text_node(text: str, parent: EnhancedDOMTreeNode | None) -> EnhancedDOMTreeNode:
			nonlocal next_node_id
			node = EnhancedDOMTreeNode(
				node_id=next_node_id,
				backend_node_id=-next_node_id,
				node_type=NodeType.TEXT_NODE,
				node_name='#text',
				node_value=text,
				attributes={},
				is_scrollable=False,
				is_visible=True,
				absolute_position=None,
				target_id=target_id,
				frame_id=None,
				session_id=None,
				content_document=None,
				shadow_root_type=None,
				shadow_roots=[],
				parent_node=parent,
				children_nodes=[],
				ax_node=None,
				snapshot_node=None,
			)
			next_node_id += 1
			return node

		def make_element_node(
			tag: str,
			backend_node_id: int,
			attributes: dict[str, str],
			rect: dict[str, Any] | None,
			parent: EnhancedDOMTreeNode | None,
			text: str | None = None,
			is_interactive: bool = False,
		) -> tuple[EnhancedDOMTreeNode, SimplifiedNode]:
			nonlocal next_node_id
			snapshot = None
			if rect:
				snapshot = EnhancedSnapshotNode(
					is_clickable=is_interactive,
					cursor_style='pointer' if is_interactive else None,
					bounds=DOMRect(
						x=float(rect.get('x') or 0),
						y=float(rect.get('y') or 0),
						width=float(rect.get('width') or 0),
						height=float(rect.get('height') or 0),
					),
					clientRects=DOMRect(
						x=float(rect.get('clientX') or rect.get('x') or 0),
						y=float(rect.get('clientY') or rect.get('y') or 0),
						width=float(rect.get('width') or 0),
						height=float(rect.get('height') or 0),
					),
					scrollRects=DOMRect(
						x=float(rect.get('x') or 0),
						y=float(rect.get('y') or 0),
						width=float(rect.get('width') or 0),
						height=float(rect.get('height') or 0),
					),
					computed_styles={},
					paint_order=None,
					stacking_contexts=None,
				)
			node = EnhancedDOMTreeNode(
				node_id=next_node_id,
				backend_node_id=backend_node_id,
				node_type=NodeType.ELEMENT_NODE,
				node_name=tag,
				node_value='',
				attributes=attributes,
				is_scrollable=False,
				is_visible=True,
				absolute_position=snapshot.bounds if snapshot else None,
				target_id=target_id,
				frame_id=None,
				session_id=None,
				content_document=None,
				shadow_root_type=None,
				shadow_roots=[],
				parent_node=parent,
				children_nodes=[],
				ax_node=None,
				snapshot_node=snapshot,
			)
			next_node_id += 1
			simplified = SimplifiedNode(original_node=node, children=[], should_display=True, is_interactive=is_interactive)
			if text:
				text_node = make_text_node(text, node)
				node.children_nodes = [text_node]
				simplified.children.append(
					SimplifiedNode(original_node=text_node, children=[], should_display=True, is_interactive=False)
				)
			if is_interactive:
				selector_map[backend_node_id] = node
			return node, simplified

		html_node, html_simple = make_element_node('html', 0, {}, None, None)
		body_node, body_simple = make_element_node('body', 0, {}, None, html_node)
		html_node.children_nodes = [body_node]
		html_simple.children.append(body_simple)

		for block in state.get('textBlocks', [])[:120]:
			text = str(block.get('text') or '').strip()
			if len(text) < 2:
				continue
			_, simple = make_element_node(
				tag=str(block.get('tag') or 'p'),
				backend_node_id=-next_node_id,
				attributes={},
				rect=block.get('rect'),
				parent=body_node,
				text=text,
				is_interactive=False,
			)
			body_simple.children.append(simple)

		for element in state.get('elements', [])[:160]:
			backend_id = int(element['id'])
			attrs = {key: str(value) for key, value in (element.get('attributes') or {}).items() if value not in (None, '')}
			attrs['data-browser-use-safari-id'] = str(backend_id)
			label = str(element.get('label') or '').strip()
			text = str(element.get('text') or '').strip()
			if label and 'aria-label' not in attrs:
				attrs['aria-label'] = label
			if 'type' not in attrs and element.get('type'):
				attrs['type'] = str(element['type'])
			if 'role' not in attrs and element.get('role'):
				attrs['role'] = str(element['role'])
			display_text = text if text and text != label else label or text or None
			node, simple = make_element_node(
				tag=str(element.get('tag') or 'div'),
				backend_node_id=backend_id,
				attributes=attrs,
				rect=element.get('rect'),
				parent=body_node,
				text=display_text,
				is_interactive=True,
			)
			body_node.children_nodes = (body_node.children_nodes or []) + [node]
			body_simple.children.append(simple)

		return SerializedDOMState(_root=html_simple, selector_map=selector_map)

	def _target_id(self, window_id: int, tab_index: int) -> str:
		return f'safari:{window_id}:{tab_index}'

	def _parse_target_id(self, target_id: str) -> tuple[int, int]:
		parts = target_id.split(':')
		if len(parts) != 3 or parts[0] != 'safari':
			raise BrowserError(f'Invalid Safari target id: {target_id!r}')
		return int(parts[1]), int(parts[2])

	def _extract_profile_label(self, window_name: str) -> str | None:
		if PROFILE_TITLE_SEPARATOR not in window_name:
			return None
		return window_name.split(PROFILE_TITLE_SEPARATOR, 1)[0].strip() or None

	def _state_extraction_script(self) -> str:
		return """
		(() => {
			const clean = value => (value || '').replace(/\\s+/g, ' ').trim();
			const rectToObject = rect => ({
				x: rect.left + window.scrollX,
				y: rect.top + window.scrollY,
				clientX: rect.left,
				clientY: rect.top,
				width: rect.width,
				height: rect.height,
			});
			const isVisible = el => {
				const style = window.getComputedStyle(el);
				if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
				const rect = el.getBoundingClientRect();
				return rect.width >= 1 && rect.height >= 1 && rect.bottom >= 0 && rect.right >= 0 && rect.top <= window.innerHeight && rect.left <= window.innerWidth;
			};
			const labelFor = el => {
				if (el.labels && el.labels.length) {
					return clean(Array.from(el.labels).map(label => label.innerText || label.textContent || '').join(' '));
				}
				return clean(el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('name') || '');
			};
			const textFor = el => {
				if (el.matches('input, textarea, select')) {
					return clean(labelFor(el) || el.value || '');
				}
				return clean(el.innerText || el.textContent || labelFor(el));
			};

			const selector = [
				'a[href]',
				'button',
				'input',
				'select',
				'textarea',
				'summary',
				'[role="button"]',
				'[role="link"]',
				'[role="textbox"]',
				'[role="searchbox"]',
				'[role="combobox"]',
				'[role="menuitem"]',
				'[contenteditable="true"]',
				'[tabindex]'
			].join(',');

			let counter = Number(document.documentElement.dataset.browserUseSafariCounter || '1');
			const elements = [];
			const seen = new Set();
			for (const el of document.querySelectorAll(selector)) {
				if (elements.length >= 160) break;
				if (!isVisible(el)) continue;
				const rect = el.getBoundingClientRect();
				const fingerprint = `${el.tagName}:${Math.round(rect.left)}:${Math.round(rect.top)}:${Math.round(rect.width)}:${Math.round(rect.height)}:${clean((el.innerText || el.textContent || '').slice(0, 80))}`;
				if (seen.has(fingerprint)) continue;
				seen.add(fingerprint);
				if (!el.dataset.browserUseSafariId) el.dataset.browserUseSafariId = String(counter++);
				const identifier = Number(el.dataset.browserUseSafariId);
				elements.push({
					id: identifier,
					tag: el.tagName.toLowerCase(),
					type: el.getAttribute('type') || '',
					role: el.getAttribute('role') || '',
					text: textFor(el).slice(0, 200),
					label: labelFor(el).slice(0, 200),
					rect: rectToObject(rect),
					attributes: {
						id: el.id || '',
						class: clean(el.className || ''),
						name: el.getAttribute('name') || '',
						type: el.getAttribute('type') || '',
						placeholder: el.getAttribute('placeholder') || '',
						value: ('value' in el && typeof el.value === 'string') ? el.value.slice(0, 200) : '',
						title: el.getAttribute('title') || '',
						role: el.getAttribute('role') || '',
						href: el.getAttribute('href') || '',
						'aria-label': el.getAttribute('aria-label') || '',
					},
				});
			}
			document.documentElement.dataset.browserUseSafariCounter = String(counter);

			const textBlocks = [];
			for (const el of document.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,label,article,section,summary')) {
				if (textBlocks.length >= 120) break;
				if (!isVisible(el)) continue;
				const text = clean(el.innerText || el.textContent || '');
				if (text.length < 2) continue;
				textBlocks.push({
					tag: el.tagName.toLowerCase(),
					text: text.slice(0, 240),
					rect: rectToObject(el.getBoundingClientRect()),
				});
			}

			const pageWidth = Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0, window.innerWidth);
			const pageHeight = Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0, window.innerHeight);
			return JSON.stringify({
				url: location.href,
				title: document.title,
				page: {
					viewportWidth: window.innerWidth,
					viewportHeight: window.innerHeight,
					pageWidth,
					pageHeight,
					scrollX: window.scrollX,
					scrollY: window.scrollY,
					pixelsAbove: window.scrollY,
					pixelsBelow: Math.max(0, pageHeight - (window.scrollY + window.innerHeight)),
				},
				elements,
				textBlocks,
			});
		})()
		"""

	def _build_keystroke_script(self, token: str) -> str | None:
		normalized = token.strip()
		key_codes = {
			'tab': 48,
			'enter': 36,
			'return': 36,
			'escape': 53,
			'esc': 53,
			'space': 49,
			'arrowdown': 125,
			'arrowup': 126,
			'arrowleft': 123,
			'arrowright': 124,
			'delete': 51,
			'backspace': 51,
		}
		modifier_map = {
			'cmd': 'command down',
			'command': 'command down',
			'ctrl': 'control down',
			'control': 'control down',
			'opt': 'option down',
			'option': 'option down',
			'alt': 'option down',
			'shift': 'shift down',
		}

		if '+' not in normalized:
			code = key_codes.get(normalized.lower())
			if code is not None:
				return f'se.keyCode({code});\n'
			return f'se.keystroke({json.dumps(normalized)});\n'

		parts = [piece.strip().lower() for piece in normalized.split('+') if piece.strip()]
		if not parts:
			return None
		key = parts[-1]
		modifiers = [modifier_map[part] for part in parts[:-1] if part in modifier_map]
		if not modifiers:
			return None
		code = key_codes.get(key)
		if code is not None:
			return f'se.keyCode({code}, {{ using: {json.dumps(modifiers)} }});\n'
		return f'se.keystroke({json.dumps(key)}, {{ using: {json.dumps(modifiers)} }});\n'

	def _read_safari_version(self) -> str:
		return _read_safari_version()

	def _read_macos_version(self) -> str:
		return _read_macos_version()

	def _version_at_least(self, version: str, minimum: str) -> bool:
		return _version_at_least(version, minimum)

	async def _run_jxa_json(self, script: str) -> Any:
		output = await self._run_jxa(script)
		try:
			return json.loads(output)
		except json.JSONDecodeError as exc:
			raise BrowserError('Safari backend returned malformed JSON from JXA.', details={'output': output[:500]}) from exc

	async def _run_jxa(self, script: str) -> str:
		return await asyncio.to_thread(self._run_jxa_sync, script)

	def _run_jxa_sync(self, script: str) -> str:
		return _run_jxa_sync(script)


def shutil_which(binary: str) -> str | None:
	"""Small local helper to avoid importing shutil just for which()."""
	for directory in os.environ.get('PATH', '').split(os.pathsep):
		candidate = Path(directory) / binary
		if candidate.exists() and os.access(candidate, os.X_OK):
			return str(candidate)
	return None
