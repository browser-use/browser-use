"""Background daemon - keeps a single BrowserSession alive.

Each daemon owns one session, identified by a session name (default: 'default').
Isolation is per-session: each gets its own socket and PID file.
Auto-exits when browser dies (polls is_cdp_connected).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.skill_cli.sessions import SessionInfo

# Configure logging before imports
logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
	handlers=[logging.StreamHandler()],
)
logger = logging.getLogger('browser_use.skill_cli.daemon')


class Daemon:
	"""Single-session daemon that manages a browser and handles CLI commands."""

	def __init__(
		self,
		headed: bool,
		profile: str | None,
		cdp_url: str | None = None,
		use_cloud: bool = False,
		cloud_timeout: int | None = None,
		cloud_proxy_country_code: str | None = None,
		cloud_profile_id: str | None = None,
		session: str = 'default',
	) -> None:
		from browser_use.skill_cli.utils import validate_session_name

		validate_session_name(session)
		self.session = session
		self.headed = headed
		self.profile = profile
		self.cdp_url = cdp_url
		self.use_cloud = use_cloud
		self.cloud_timeout = cloud_timeout
		self.cloud_proxy_country_code = cloud_proxy_country_code
		self.cloud_profile_id = cloud_profile_id
		self.running = True
		self._server: asyncio.Server | None = None
		self._shutdown_event = asyncio.Event()
		self._session: SessionInfo | None = None
		self._shutdown_task: asyncio.Task | None = None
		self._browser_watchdog_task: asyncio.Task | None = None

	async def _get_or_create_session(self) -> SessionInfo:
		"""Lazy-create the single session on first command."""
		if self._session is not None:
			return self._session

		from browser_use.skill_cli.sessions import SessionInfo, create_browser_session

		logger.info(
			f'Creating session (headed={self.headed}, profile={self.profile}, cdp_url={self.cdp_url}, use_cloud={self.use_cloud})'
		)

		bs = await create_browser_session(
			self.headed,
			self.profile,
			self.cdp_url,
			use_cloud=self.use_cloud,
			cloud_timeout=self.cloud_timeout,
			cloud_proxy_country_code=self.cloud_proxy_country_code,
			cloud_profile_id=self.cloud_profile_id,
		)
		await bs.start()

		self._session = SessionInfo(
			name=self.session,
			headed=self.headed,
			profile=self.profile,
			cdp_url=self.cdp_url,
			browser_session=bs,
			use_cloud=self.use_cloud,
		)
		self._browser_watchdog_task = asyncio.create_task(self._watch_browser())
		return self._session

	async def _watch_browser(self) -> None:
		"""Poll BrowserSession.is_cdp_connected every 2s. Shutdown when browser dies."""
		while self.running:
			await asyncio.sleep(2.0)
			if self._session and not self._session.browser_session.is_cdp_connected:
				logger.info('Browser disconnected, shutting down daemon')
				await self.shutdown()
				return

	async def handle_connection(
		self,
		reader: asyncio.StreamReader,
		writer: asyncio.StreamWriter,
	) -> None:
		"""Handle a single client request (one command per connection)."""
		try:
			line = await asyncio.wait_for(reader.readline(), timeout=300)
			if not line:
				return

			request = {}
			try:
				request = json.loads(line.decode())
				response = await self.dispatch(request)
			except json.JSONDecodeError as e:
				response = {'id': '', 'success': False, 'error': f'Invalid JSON: {e}'}
			except Exception as e:
				logger.exception(f'Error handling request: {e}')
				response = {'id': '', 'success': False, 'error': str(e)}

			writer.write((json.dumps(response) + '\n').encode())
			await writer.drain()

			if request.get('action') == 'shutdown':
				await self.shutdown()

		except TimeoutError:
			logger.debug('Connection timeout')
		except Exception as e:
			logger.exception(f'Connection error: {e}')
		finally:
			writer.close()
			try:
				await writer.wait_closed()
			except Exception:
				pass

	async def dispatch(self, request: dict) -> dict:
		"""Route to command handlers."""
		action = request.get('action', '')
		params = request.get('params', {})
		req_id = request.get('id', '')

		logger.info(f'Dispatch: {action} (id={req_id})')

		try:
			# Handle shutdown
			if action == 'shutdown':
				return {'id': req_id, 'success': True, 'data': {'shutdown': True}}

			# Handle ping — returns daemon config for mismatch detection
			if action == 'ping':
				return {
					'id': req_id,
					'success': True,
					'data': {
						'session': self.session,
						'headed': self.headed,
						'profile': self.profile,
						'cdp_url': self.cdp_url,
						'use_cloud': self.use_cloud,
					},
				}

			# Handle connect — forces immediate session creation (used by cloud connect)
			if action == 'connect':
				session = await self._get_or_create_session()
				bs = session.browser_session
				result_data: dict = {'status': 'connected'}
				if bs.cdp_url:
					result_data['cdp_url'] = bs.cdp_url
				if self.use_cloud and bs.cdp_url:
					from urllib.parse import quote

					result_data['live_url'] = f'https://live.browser-use.com/?wss={quote(bs.cdp_url, safe="")}'
				return {'id': req_id, 'success': True, 'data': result_data}

			from browser_use.skill_cli.commands import browser, python_exec

			# Get or create the single session
			session = await self._get_or_create_session()

			# Dispatch to handler
			if action in browser.COMMANDS:
				result = await browser.handle(action, session, params)
			elif action == 'python':
				result = await python_exec.handle(session, params)
			else:
				return {'id': req_id, 'success': False, 'error': f'Unknown action: {action}'}

			return {'id': req_id, 'success': True, 'data': result}

		except Exception as e:
			logger.exception(f'Error dispatching {action}: {e}')
			return {'id': req_id, 'success': False, 'error': str(e)}

	async def run(self) -> None:
		"""Listen on Unix socket (or TCP on Windows) with PID file.

		Note: we do NOT unlink the socket in our finally block. If a replacement
		daemon was spawned during our shutdown, it already bound a new socket at
		the same path — unlinking here would delete *its* socket, orphaning it.
		Stale sockets are cleaned up by is_daemon_alive() and by the next
		daemon's startup (unlink before bind).
		"""
		import os

		from browser_use.skill_cli.utils import get_pid_path, get_socket_path

		# Setup signal handlers
		loop = asyncio.get_running_loop()

		def signal_handler():
			if not self._shutdown_task or self._shutdown_task.done():
				self._shutdown_task = asyncio.create_task(self.shutdown())

		for sig in (signal.SIGINT, signal.SIGTERM):
			try:
				loop.add_signal_handler(sig, signal_handler)
			except NotImplementedError:
				pass  # Windows doesn't support add_signal_handler

		if hasattr(signal, 'SIGHUP'):
			try:
				loop.add_signal_handler(signal.SIGHUP, signal_handler)
			except NotImplementedError:
				pass

		sock_path = get_socket_path(self.session)
		pid_path = get_pid_path(self.session)
		logger.info(f'Session: {self.session}, Socket: {sock_path}')

		if sock_path.startswith('tcp://'):
			# Windows: TCP server
			_, hostport = sock_path.split('://', 1)
			host, port = hostport.split(':')
			self._server = await asyncio.start_server(
				self.handle_connection,
				host,
				int(port),
				reuse_address=True,
			)
			logger.info(f'Listening on TCP {host}:{port}')
		else:
			# Unix: socket server
			Path(sock_path).unlink(missing_ok=True)
			self._server = await asyncio.start_unix_server(
				self.handle_connection,
				sock_path,
			)
			logger.info(f'Listening on Unix socket {sock_path}')

		# Write PID file after server is bound
		my_pid = str(os.getpid())
		pid_path.write_text(my_pid)

		try:
			async with self._server:
				await self._shutdown_event.wait()
				# Wait for shutdown to finish browser cleanup before exiting
				if self._shutdown_task:
					await self._shutdown_task
		except asyncio.CancelledError:
			pass
		finally:
			# Conditionally delete PID file only if it still contains our PID
			try:
				if pid_path.read_text().strip() == my_pid:
					pid_path.unlink(missing_ok=True)
			except (OSError, ValueError):
				pass
			logger.info('Daemon stopped')

	async def shutdown(self) -> None:
		"""Graceful shutdown.

		Order matters: close the server first to release the socket/port
		immediately, so a replacement daemon can bind without waiting for
		browser cleanup. Then kill the browser session.
		"""
		logger.info('Shutting down daemon...')
		self.running = False
		self._shutdown_event.set()

		if self._browser_watchdog_task:
			self._browser_watchdog_task.cancel()

		if self._server:
			self._server.close()

		if self._session:
			try:
				# Only kill the browser if the daemon launched it.
				# For external connections (--connect, --cdp-url, cloud), just disconnect.
				if self.cdp_url or self.use_cloud:
					await self._session.browser_session.stop()
				else:
					await self._session.browser_session.kill()
			except Exception as e:
				logger.warning(f'Error closing session: {e}')
			self._session = None


def main() -> None:
	"""Main entry point for daemon process."""
	parser = argparse.ArgumentParser(description='Browser-use daemon')
	parser.add_argument('--session', default='default', help='Session name (default: "default")')
	parser.add_argument('--headed', action='store_true', help='Show browser window')
	parser.add_argument('--profile', help='Chrome profile (triggers real Chrome mode)')
	parser.add_argument('--cdp-url', help='CDP URL to connect to')
	parser.add_argument('--use-cloud', action='store_true', help='Use cloud browser')
	parser.add_argument('--cloud-timeout', type=int, help='Cloud browser timeout in seconds')
	parser.add_argument('--cloud-proxy-country', help='Cloud browser proxy country code')
	parser.add_argument('--cloud-profile-id', help='Cloud browser profile ID')
	args = parser.parse_args()

	logger.info(
		f'Starting daemon: session={args.session}, headed={args.headed}, profile={args.profile}, cdp_url={args.cdp_url}, use_cloud={args.use_cloud}'
	)

	daemon = Daemon(
		headed=args.headed,
		profile=args.profile,
		cdp_url=args.cdp_url,
		use_cloud=args.use_cloud,
		cloud_timeout=args.cloud_timeout,
		cloud_proxy_country_code=args.cloud_proxy_country,
		cloud_profile_id=args.cloud_profile_id,
		session=args.session,
	)

	try:
		asyncio.run(daemon.run())
	except KeyboardInterrupt:
		logger.info('Interrupted')
	except Exception as e:
		logger.exception(f'Daemon error: {e}')
		sys.exit(1)


if __name__ == '__main__':
	main()
