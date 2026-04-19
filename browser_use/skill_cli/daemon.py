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
import os
import signal
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
		cloud_profile_id: str | None = None,
		cloud_proxy_country_code: str | None = None,
		cloud_timeout: int | None = None,
		session: str = 'default',
	) -> None:
		from browser_use.skill_cli.utils import validate_session_name

		validate_session_name(session)
		self.session = session
		self.headed = headed
		self.profile = profile
		self.cdp_url = cdp_url
		self.use_cloud = use_cloud
		self.cloud_profile_id = cloud_profile_id
		self.cloud_proxy_country_code = cloud_proxy_country_code
		self.cloud_timeout = cloud_timeout
		self.running = True
		self._server: asyncio.Server | None = None
		self._shutdown_event = asyncio.Event()
		self._session: SessionInfo | None = None
		self._shutdown_task: asyncio.Task | None = None
		self._browser_watchdog_task: asyncio.Task | None = None
		self._session_lock = asyncio.Lock()
		self._last_command_time: float = 0.0
		self._idle_timeout: float = 30 * 60.0  # 30 minutes
		self._idle_watchdog_task: asyncio.Task | None = None
		self._is_shutting_down: bool = False
		self._auth_token: str = ''

	def _write_state(self, phase: str) -> None:
		"""Atomically write session state file for CLI observability."""
		import time

		from browser_use.skill_cli.utils import get_home_dir

		state = {
			'phase': phase,
			'pid': os.getpid(),
			'updated_at': time.time(),
			'config': {
				'headed': self.headed,
				'profile': self.profile,
				'cdp_url': self.cdp_url,
				'use_cloud': self.use_cloud,
			},
		}
		state_path = get_home_dir() / f'{self.session}.state.json'
		tmp_path = state_path.with_suffix('.state.json.tmp')
		try:
			with open(tmp_path, 'w') as f:
				json.dump(state, f)
				f.flush()
				os.fsync(f.fileno())
			os.replace(tmp_path, state_path)
		except OSError as e:
			logger.debug(f'Failed to write state file: {e}')

	def _request_shutdown(self) -> None:
		"""Request shutdown exactly once. Safe from any context."""
		if self._is_shutting_down:
			return
		self._is_shutting_down = True
		self._shutdown_task = asyncio.create_task(self._shutdown())

	async def _get_or_create_session(self) -> SessionInfo:
		"""Lazy-create the single session on first command."""
		if self._session is not None:
			return self._session

		async with self._session_lock:
			# Double-check after acquiring lock
			if self._session is not None:
				return self._session

			from browser_use.skill_cli.sessions import SessionInfo, create_browser_session

			logger.info(
				f'Creating session (headed={self.headed}, profile={self.profile}, cdp_url={self.cdp_url}, use_cloud={self.use_cloud})'
			)

			self._write_state('starting')

			bs = await create_browser_session(
				self.headed,
				self.profile,
				self.cdp_url,
				use_cloud=self.use_cloud,
				cloud_profile_id=self.cloud_profile_id,
				cloud_proxy_country_code=self.cloud_proxy_country_code,
				cloud_timeout=self.cloud_timeout,
			)

			try:
				await bs.start()
				self._write_state('starting')  # refresh updated_at after bs.start() returns

				# Wait for Chrome to stabilize after CDP setup before accepting commands
				try:
					await bs.get_browser_state_summary()
				except Exception:
					pass

				# Create action handler for direct command execution (no event bus)
				from browser_use.skill_cli.actions import ActionHandler

				actions = ActionHandler(bs)

				self._session = SessionInfo(
					name=self.session,
					headed=self.headed,
					profile=self.profile,
					cdp_url=self.cdp_url,
					browser_session=bs,
					actions=actions,
					use_cloud=self.use_cloud,
				)
				self._browser_watchdog_task = asyncio.create_task(self._watch_browser())

				# Start idle timeout watchdog
				self._idle_watchdog_task = asyncio.create_task(self._watch_idle())

			except Exception:
				# Startup failed — rollback browser resources
				logger.exception('Session startup failed, rolling back')
				self._write_state('failed')
				try:
					if self.use_cloud and hasattr(bs, '_cloud_browser_client') and bs._cloud_browser_client.current_session_id:
						await asyncio.wait_for(bs._cloud_browser_client.stop_browser(), timeout=10.0)
					elif not self.cdp_url and not self.use_cloud:
						await asyncio.wait_for(bs.kill(), timeout=10.0)
					else:
						await asyncio.wait_for(bs.stop(), timeout=10.0)
				except Exception as cleanup_err:
					logger.debug(f'Rollback cleanup error: {cleanup_err}')
				raise

			self._write_state('running')
			return self._session

	async def _watch_browser(self) -> None:
		"""Poll BrowserSession.is_cdp_connected every 2s. Shutdown when browser dies.

		Skips checks while the BrowserSession is reconnecting. If reconnection fails,
		next poll will see is_cdp_connected=False and trigger shutdown.
		"""
		while self.running:
			await asyncio.sleep(2.0)
			if not self._session:
				continue
			bs = self._session.browser_session
			# Don't shut down while a reconnection attempt is in progress
			if bs.is_reconnecting:
				continue
			if not bs.is_cdp_connected:
				logger.info('Browser disconnected, shutting down daemon')
				self._request_shutdown()
				return

	async def _watch_idle(self) -> None:
		"""Shutdown daemon after idle_timeout seconds of no commands."""
		while self.running:
			await asyncio.sleep(60.0)
			if self._last_command_time > 0:
				import time

				idle = time.monotonic() - self._last_command_time
				if idle >= self._idle_timeout:
					logger.info(f'Daemon idle for {idle:.0f}s, shutting down')
					self._request_shutdown()
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
				import hmac

				request = json.loads(line.decode())
				req_id = request.get('id', '')
				# Reject requests that don't carry the correct auth token.
				# Use hmac.compare_digest to prevent timing-oracle attacks.
				if self._auth_token and not hmac.compare_digest(
					request.get('token', ''),
					self._auth_token,
				):
					response = {'id': req_id, 'success': False, 'error': 'Unauthorized'}
				else:
					response = await self.dispatch(request)
			except json.JSONDecodeError as e:
				response = {'id': '', 'success': False, 'error': f'Invalid JSON: {e}'}
			except Exception as e:
				logger.exception(f'Error handling request: {e}')
				response = {'id': '', 'success': False, 'error': str(e)}

			writer.write((json.dumps(response) + '\n').encode())
			await writer.drain()

			if response.get('success') and request.get('action') == 'shutdown':
				self._request_shutdown()

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
		import time

		self._last_command_time = time.monotonic()

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
				# Return live CDP URL (may differ from constructor arg for cloud sessions)
				live_cdp_url = self.cdp_url
				if self._session and self._session.browser_session.cdp_url:
					live_cdp_url = self._session.browser_session.cdp_url
				return {
					'id': req_id,
					'success': True,
					'data': {
						'session': self.session,
						'pid': os.getpid(),
						'headed': self.headed,
						'profile': self.profile,
						'cdp_url': live_cdp_url,
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
		import secrets

		from browser_use.skill_cli.utils import get_auth_token_path, get_pid_path, get_socket_path

		self._write_state('initializing')

		# Generate and persist a per-session auth token.
		# The client reads this file to authenticate its requests, preventing
		# any other local process from sending commands to the daemon socket.
		# Create the temp file with 0o600 at open() time to avoid a permission
		# race window where the file exists but is not yet restricted.
		# Raise on failure — running without a readable token file leaves the
		# daemon permanently unauthorized for all clients.
		self._auth_token = secrets.token_hex(32)
		token_path = get_auth_token_path(self.session)
		tmp_token = token_path.with_suffix('.token.tmp')
		fd = os.open(str(tmp_token), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
		try:
			with os.fdopen(fd, 'w') as f:
				f.write(self._auth_token)
		except OSError:
			try:
				tmp_token.unlink(missing_ok=True)
			except OSError:
				pass
			raise
		os.replace(tmp_token, token_path)

		# Setup signal handlers
		loop = asyncio.get_running_loop()

		def signal_handler():
			self._request_shutdown()

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
		self._write_state('ready')

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

	async def _shutdown(self) -> None:
		"""Graceful shutdown. Only called via _request_shutdown().

		Order matters: close the server first to release the socket/port
		immediately, so a replacement daemon can bind without waiting for
		browser cleanup. Then kill the browser session.
		"""
		logger.info('Shutting down daemon...')
		self._write_state('shutting_down')
		self.running = False
		self._shutdown_event.set()

		if self._browser_watchdog_task:
			self._browser_watchdog_task.cancel()

		if self._idle_watchdog_task:
			self._idle_watchdog_task.cancel()

		if self._server:
			self._server.close()

		if self._session:
			try:
				# Only kill the browser if the daemon launched it.
				# For external connections (--connect, --cdp-url, cloud), just disconnect.
				# Timeout ensures daemon exits even if CDP calls hang on a dead connection
				if self.cdp_url or self.use_cloud:
					await asyncio.wait_for(self._session.browser_session.stop(), timeout=10.0)
				else:
					await asyncio.wait_for(self._session.browser_session.kill(), timeout=10.0)
			except TimeoutError:
				logger.warning('Browser cleanup timed out after 10s, forcing exit')
			except Exception as e:
				logger.warning(f'Error closing session: {e}')
			self._session = None

		# Delete PID and auth token files last, right before exit.
		import os

		from browser_use.skill_cli.utils import get_auth_token_path, get_pid_path

		pid_path = get_pid_path(self.session)
		try:
			if pid_path.exists() and pid_path.read_text().strip() == str(os.getpid()):
				pid_path.unlink(missing_ok=True)
		except (OSError, ValueError):
			pass

		get_auth_token_path(self.session).unlink(missing_ok=True)

		self._write_state('stopped')

		# Force exit — the asyncio server's __aexit__ hangs waiting for the
		# handle_connection() call that triggered this shutdown to return.
		logger.info('Daemon process exiting')
		os._exit(0)


def main() -> None:
	"""Main entry point for daemon process."""
	parser = argparse.ArgumentParser(description='Browser-use daemon')
	parser.add_argument('--session', default='default', help='Session name (default: "default")')
	parser.add_argument('--headed', action='store_true', help='Show browser window')
	parser.add_argument('--profile', help='Chrome profile (triggers real Chrome mode)')
	parser.add_argument('--cdp-url', help='CDP URL to connect to')
	parser.add_argument('--use-cloud', action='store_true', help='Use cloud browser')
	parser.add_argument('--cloud-profile-id', help='Cloud browser profile ID')
	parser.add_argument('--cloud-proxy-country', help='Cloud browser proxy country code')
	parser.add_argument('--cloud-timeout', type=int, help='Cloud browser timeout in minutes')
	args = parser.parse_args()

	logger.info(
		f'Starting daemon: session={args.session}, headed={args.headed}, profile={args.profile}, cdp_url={args.cdp_url}, use_cloud={args.use_cloud}'
	)

	daemon = Daemon(
		headed=args.headed,
		profile=args.profile,
		cdp_url=args.cdp_url,
		use_cloud=args.use_cloud,
		cloud_profile_id=args.cloud_profile_id,
		cloud_proxy_country_code=args.cloud_proxy_country,
		cloud_timeout=args.cloud_timeout,
		session=args.session,
	)

	exit_code = 0
	try:
		asyncio.run(daemon.run())
	except KeyboardInterrupt:
		logger.info('Interrupted')
	except Exception as e:
		logger.exception(f'Daemon error: {e}')
		exit_code = 1
	finally:
		# Write failed state if we crashed without a clean shutdown
		if not daemon._is_shutting_down:
			try:
				daemon._write_state('failed')
			except Exception:
				pass
		# asyncio.run() may hang trying to cancel lingering tasks
		# Force-exit to prevent the daemon from becoming an orphan
		logger.info('Daemon process exiting')
		os._exit(exit_code)


if __name__ == '__main__':
	main()
