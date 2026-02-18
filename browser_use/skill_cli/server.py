"""Session server - keeps BrowserSession instances alive.

This server runs as a background process, managing browser sessions and
handling commands from the CLI. It uses Unix sockets (or TCP on Windows)
for IPC communication.
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import IO

import portalocker

# Configure logging before imports
logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
	handlers=[logging.StreamHandler()],
)
logger = logging.getLogger('browser_use.skill_cli.server')


class SessionServer:
	"""Server that manages browser sessions and handles CLI commands."""

	def __init__(
		self,
		session_name: str,
		browser_mode: str,
		headed: bool,
		profile: str | None,
	) -> None:
		self.session_name = session_name
		self.browser_mode = browser_mode
		self.headed = headed
		self.profile = profile
		self.running = True
		self._server: asyncio.Server | None = None
		self._shutdown_event: asyncio.Event | None = None
		self._lock_file: IO | None = None

		# Lazy import to avoid loading everything at startup
		from browser_use.skill_cli.sessions import SessionRegistry

		self.registry = SessionRegistry()

	async def handle_connection(
		self,
		reader: asyncio.StreamReader,
		writer: asyncio.StreamWriter,
	) -> None:
		"""Handle a client connection."""
		addr = writer.get_extra_info('peername')
		logger.debug(f'Connection from {addr}')

		try:
			while self.running:
				try:
					line = await asyncio.wait_for(reader.readline(), timeout=300)  # 5 min timeout
				except TimeoutError:
					logger.debug(f'Connection timeout from {addr}')
					break

				if not line:
					break

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

				# Check for shutdown command
				if request.get('action') == 'shutdown':
					await self.shutdown()
					break

		except Exception as e:
			logger.exception(f'Connection error: {e}')
		finally:
			writer.close()
			try:
				await writer.wait_closed()
			except Exception:
				pass

	async def dispatch(self, request: dict) -> dict:
		"""Dispatch command to appropriate handler."""
		action = request.get('action', '')
		params = request.get('params', {})
		req_id = request.get('id', '')

		logger.info(f'Dispatch: {action} (id={req_id})')

		try:
			# Import command handlers
			from browser_use.skill_cli.commands import agent, browser, python_exec, session

			# Handle shutdown
			if action == 'shutdown':
				return {'id': req_id, 'success': True, 'data': {'shutdown': True}}

			# Session commands don't need a browser session
			if action in session.COMMANDS:
				result = await session.handle(action, self.session_name, self.registry, params)
				# Check if command wants to shutdown server
				if result.get('_shutdown'):
					asyncio.create_task(self.shutdown())
				return {'id': req_id, 'success': True, 'data': result}

			# Get or create session for browser commands
			session_info = await self.registry.get_or_create(
				self.session_name,
				self.browser_mode,
				self.headed,
				self.profile,
			)

			# Dispatch to handler
			if action in browser.COMMANDS:
				result = await browser.handle(action, session_info, params)
			elif action == 'python':
				result = await python_exec.handle(session_info, params)
			elif action == 'run':
				result = await agent.handle(session_info, params)
			else:
				return {'id': req_id, 'success': False, 'error': f'Unknown action: {action}'}

			return {'id': req_id, 'success': True, 'data': result}

		except Exception as e:
			logger.exception(f'Error dispatching {action}: {e}')
			return {'id': req_id, 'success': False, 'error': str(e)}

	async def shutdown(self) -> None:
		"""Graceful shutdown."""
		logger.info('Shutting down server...')
		self.running = False

		# Signal the shutdown event
		if self._shutdown_event:
			self._shutdown_event.set()

		# Close all sessions
		await self.registry.close_all()

		# Stop the server
		if self._server:
			self._server.close()
			await self._server.wait_closed()

		# Clean up files
		from browser_use.skill_cli.utils import cleanup_session_files

		cleanup_session_files(self.session_name)

	async def run(self) -> None:
		"""Run the server."""
		from browser_use.skill_cli.utils import get_lock_path, get_pid_path, get_socket_path

		# Acquire exclusive lock BEFORE writing PID - this prevents race conditions
		lock_path = get_lock_path(self.session_name)
		lock_path.parent.mkdir(parents=True, exist_ok=True)
		lock_path.touch(exist_ok=True)

		self._lock_file = open(lock_path, 'r+')  # noqa: ASYNC230 - blocking ok at startup
		try:
			portalocker.lock(self._lock_file, portalocker.LOCK_EX | portalocker.LOCK_NB)
		except portalocker.LockException:
			logger.error(f'Another server is already running for session: {self.session_name}')
			self._lock_file.close()
			self._lock_file = None
			sys.exit(1)

		logger.info(f'Acquired exclusive lock for session: {self.session_name}')

		# NOW safe to write PID file
		pid_path = get_pid_path(self.session_name)
		pid_path.write_text(str(os.getpid()))
		logger.info(f'PID file: {pid_path}')

		# Setup signal handlers
		loop = asyncio.get_running_loop()

		def signal_handler():
			asyncio.create_task(self.shutdown())

		for sig in (signal.SIGINT, signal.SIGTERM):
			try:
				loop.add_signal_handler(sig, signal_handler)
			except NotImplementedError:
				# Windows doesn't support add_signal_handler
				pass

		# Also handle SIGHUP on Unix
		if hasattr(signal, 'SIGHUP'):
			try:
				loop.add_signal_handler(signal.SIGHUP, signal_handler)
			except NotImplementedError:
				pass

		# Get socket path
		sock_path = get_socket_path(self.session_name)
		logger.info(f'Socket: {sock_path}')

		# Start server
		if sock_path.startswith('tcp://'):
			# Windows: TCP server
			_, hostport = sock_path.split('://', 1)
			host, port = hostport.split(':')
			self._server = await asyncio.start_server(
				self.handle_connection,
				host,
				int(port),
				reuse_address=True,  # Allow rebinding ports in TIME_WAIT state
			)
			logger.info(f'Listening on TCP {host}:{port}')
		else:
			# Unix: socket server
			# Remove stale socket file
			sock_file = Path(sock_path)
			if sock_file.exists():
				sock_file.unlink()

			self._server = await asyncio.start_unix_server(
				self.handle_connection,
				sock_path,
			)
			logger.info(f'Listening on Unix socket {sock_path}')

		# Run until shutdown
		self._shutdown_event = asyncio.Event()
		try:
			async with self._server:
				await self._shutdown_event.wait()
		except asyncio.CancelledError:
			pass
		finally:
			# Release lock on shutdown
			if self._lock_file:
				try:
					portalocker.unlock(self._lock_file)
					self._lock_file.close()
				except Exception:
					pass
				self._lock_file = None
			logger.info('Server stopped')


def main() -> None:
	"""Main entry point for server process."""
	parser = argparse.ArgumentParser(description='Browser-use session server')
	parser.add_argument('--session', required=True, help='Session name')
	parser.add_argument('--browser', default='chromium', choices=['chromium', 'real', 'remote'])
	parser.add_argument('--headed', action='store_true', help='Show browser window')
	parser.add_argument('--profile', help='Chrome profile (real browser mode)')
	args = parser.parse_args()

	logger.info(f'Starting server for session: {args.session}')
	logger.info(f'Browser mode: {args.browser}, headed: {args.headed}')

	server = SessionServer(
		session_name=args.session,
		browser_mode=args.browser,
		headed=args.headed,
		profile=args.profile,
	)

	try:
		asyncio.run(server.run())
	except KeyboardInterrupt:
		logger.info('Interrupted')
	except Exception as e:
		logger.exception(f'Server error: {e}')
		sys.exit(1)


if __name__ == '__main__':
	main()
