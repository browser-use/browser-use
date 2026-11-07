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
from backend.server import app  # noqa: E402


def _free_port() -> int:
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		sock.bind(('127.0.0.1', 0))
		return int(sock.getsockname()[1])


def main() -> None:
	port = _free_port()
	config = uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning')
	server = uvicorn.Server(config)

	if os.environ.get('BROWSER_BUDDY_SERVER_ONLY') == '1':
		print(f'BrowserBuddy Studio running at http://127.0.0.1:{port}')
		server.run()
		return

	thread = threading.Thread(target=server.run, daemon=True)
	thread.start()

	for _ in range(100):
		if server.started:
			break
		time.sleep(0.1)

	webview.create_window(
		'BrowserBuddy',
		f'http://127.0.0.1:{port}',
		width=1320,
		height=880,
		min_size=(1040, 720),
		background_color='#0b0f17',
		text_select=True,
	)
	webview.start(
		private_mode=False,
		storage_path=str(APP_SUPPORT_DIR / 'webview'),
	)
	server.should_exit = True


if __name__ == '__main__':
	main()
