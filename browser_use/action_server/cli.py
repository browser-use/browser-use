#!/usr/bin/env python3
"""
Browser Action Server CLI entry point.

This script is called by the launcher to start the server in a background process.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Add browser_use to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def run_server(host: str, port: int, debug: bool, user_data_dir: str | None = None) -> None:
	"""Run the Browser Action Server"""

	# Set up logging
	logging.basicConfig(
		level=logging.DEBUG if debug else logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
	)

	logger = logging.getLogger(__name__)

	try:
		from browser_use.action_server.service import BrowserActionServer

		server = BrowserActionServer(host=host, port=port, debug=debug, user_data_dir=user_data_dir)

		# Set up signal handlers for graceful shutdown
		shutdown_event = asyncio.Event()

		def signal_handler(signum, frame):
			logger.info(f'Received signal {signum}, shutting down...')
			shutdown_event.set()

		signal.signal(signal.SIGINT, signal_handler)
		signal.signal(signal.SIGTERM, signal_handler)

		# Start server
		await server.start()
		logger.info(f'Browser Action Server running on {host}:{port}')

		# Wait for shutdown signal
		await shutdown_event.wait()

		# Stop server
		await server.stop()
		logger.info('Browser Action Server stopped')

	except KeyboardInterrupt:
		logger.info('Received keyboard interrupt, shutting down...')
	except Exception as e:
		logger.error(f'Server error: {e}', exc_info=True)
		sys.exit(1)


def main():
	"""CLI entry point"""
	import argparse

	parser = argparse.ArgumentParser(description='Browser Action Server')
	parser.add_argument('--host', default='127.0.0.1', help='Server host (default: 127.0.0.1)')
	parser.add_argument('--port', type=int, default=8766, help='Server port (default: 8766)')
	parser.add_argument('--debug', action='store_true', help='Enable debug logging')
	parser.add_argument('--user-data-dir', help='Browser user data directory for persistent sessions')

	args = parser.parse_args()

	# Check dependencies
	try:
		import fastapi  # noqa: F401
		import playwright  # noqa: F401
		import uvicorn  # noqa: F401
	except ImportError as e:
		print(f'❌ Missing required dependency: {e}')
		print('Install with: pip install fastapi uvicorn playwright')
		print('Then run: playwright install chromium')
		sys.exit(1)

	# Run server
	try:
		asyncio.run(run_server(args.host, args.port, args.debug, args.user_data_dir))
	except KeyboardInterrupt:
		print('\n✅ Server stopped')


if __name__ == '__main__':
	main()
