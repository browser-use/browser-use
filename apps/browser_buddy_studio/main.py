# pyright: reportMissingImports=false, reportMissingTypeStubs=false
from __future__ import annotations

import os
import socket
import threading
import time

from backend.config import APP_SUPPORT_DIR, prepare_runtime

prepare_runtime()

import uvicorn  # noqa: E402
import webview  # noqa: E402
from backend.server import app, shutdown_runtime  # noqa: E402


class ClipboardApi:
	"""Native clipboard bridge because WKWebView exposes no navigator.clipboard here."""

	def copy(self, text: str) -> bool:
		try:
			from AppKit import NSPasteboard

			pasteboard = NSPasteboard.generalPasteboard()
			pasteboard.clearContents()
			return bool(pasteboard.setString_forType_(str(text), 'public.utf8-plain-text'))
		except Exception:
			return False

	def paste(self) -> str:
		try:
			from AppKit import NSPasteboard

			pasteboard = NSPasteboard.generalPasteboard()
			return pasteboard.stringForType_('public.utf8-plain-text') or ''
		except Exception:
			return ''

	def quit(self) -> bool:
		"""Quit the app after in-app data cleanup, without leaving helpers behind."""
		threading.Thread(target=webview.destroy_window, daemon=True).start()
		return True


def _free_port() -> int:
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.bind(('127.0.0.1', 0))
		return int(sock.getsockname()[1])


def _resolve_port() -> int:
	"""Allow the build script's smoke test (and debugging) to pin a port."""
	raw = os.environ.get('BROWSER_BUDDY_PORT')
	if raw:
		return int(raw)
	return _free_port()


def _enable_native_clipboard() -> None:
	"""Let WKWebView handle Cmd+C/V and the right-click menu natively.

	PyWebView's Cocoa backend intercepts clipboard shortcuts and clears the
	default context menu, which breaks copy/paste in text inputs on macOS.
	"""
	try:
		from webview.platforms.cocoa import AppKit, BrowserView

		def will_open_menu(self, menu, event):
			return None

		original_key_down = BrowserView.WebKitHost.keyDown_

		def key_down(self, event):
			try:
				if event.modifierFlags() & AppKit.NSCommandKeyMask:
					char = (event.characters() or '').lower()
					if char in ('c', 'v', 'x', 'a', 'z'):
						return super(BrowserView.WebKitHost, self).keyDown_(event)
			except Exception:
				pass
			return original_key_down(self, event)

		BrowserView.WebKitHost.willOpenMenu_withEvent_ = will_open_menu
		BrowserView.WebKitHost.keyDown_ = key_down
	except Exception:
		return


def main() -> None:
	port = _resolve_port()
	config = uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning')
	server = uvicorn.Server(config)

	if os.environ.get('BROWSER_BUDDY_SERVER_ONLY') == '1':
		print(f'BrowserBuddy Studio running at http://127.0.0.1:{port}')
		try:
			server.run()
		finally:
			shutdown_runtime()
		return

	thread = threading.Thread(target=server.run, daemon=True)
	thread.start()

	for _ in range(100):
		if server.started:
			break
		time.sleep(0.1)

	_enable_native_clipboard()
	webview.create_window(
		'BrowserBuddy',
		f'http://127.0.0.1:{port}',
		width=1320,
		height=880,
		min_size=(1040, 720),
		background_color='#ffffff',
		text_select=True,
		js_api=ClipboardApi(),
	)
	try:
		webview.start(
			private_mode=False,
			storage_path=str(APP_SUPPORT_DIR / 'webview'),
		)
	finally:
		server.should_exit = True
		shutdown_runtime()


if __name__ == '__main__':
	main()
