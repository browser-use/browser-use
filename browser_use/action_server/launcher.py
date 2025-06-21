"""
Browser Action Server launcher utilities.

Provides functions for Claude Code to start/stop the action server
in a non-blocking way.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx


def is_server_running(host: str = '127.0.0.1', port: int = 8766, timeout: float = 2.0) -> bool:
	"""
	Check if the Browser Action Server is already running.
	
	Args:
		host: Server host
		port: Server port  
		timeout: Request timeout in seconds
		
	Returns:
		True if server is running and responsive, False otherwise
	"""
	try:
		with httpx.Client(timeout=timeout) as client:
			response = client.get(f'http://{host}:{port}/health')
			return response.status_code == 200
	except Exception:
		return False


async def async_is_server_running(host: str = '127.0.0.1', port: int = 8766, timeout: float = 2.0) -> bool:
	"""
	Async version of is_server_running.
	
	Args:
		host: Server host
		port: Server port
		timeout: Request timeout in seconds
		
	Returns:
		True if server is running and responsive, False otherwise
	"""
	try:
		async with httpx.AsyncClient(timeout=timeout) as client:
			response = await client.get(f'http://{host}:{port}/health')
			return response.status_code == 200
	except Exception:
		return False


def start_server_background(
	host: str = '127.0.0.1', 
	port: int = 8766, 
	debug: bool = False,
	wait_for_start: bool = True,
	max_wait_time: float = 10.0
) -> subprocess.Popen | None:
	"""
	Start the Browser Action Server in background process.
	
	This is the non-blocking way for Claude Code to start the server.
	
	Args:
		host: Server host
		port: Server port
		debug: Enable debug logging
		wait_for_start: Wait for server to be responsive before returning
		max_wait_time: Maximum time to wait for server startup
		
	Returns:
		Subprocess handle if started successfully, None if already running or failed
	"""
	# Check if already running
	if is_server_running(host, port):
		print(f'✅ Browser Action Server already running on {host}:{port}')
		return None
	
	try:
		# Get path to this script
		script_path = Path(__file__).parent / 'cli.py'
		
		# Build command
		cmd = [
			sys.executable, str(script_path),
			'--host', host,
			'--port', str(port)
		]
		
		if debug:
			cmd.append('--debug')
		
		# Start process in background
		process = subprocess.Popen(
			cmd,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True
		)
		
		print(f'🚀 Starting Browser Action Server on {host}:{port}...')
		
		if wait_for_start:
			# Wait for server to become responsive
			start_time = time.time()
			while time.time() - start_time < max_wait_time:
				if is_server_running(host, port):
					print(f'✅ Browser Action Server started successfully!')
					return process
				time.sleep(0.5)
			
			# If we get here, server didn't start in time
			print(f'⚠️ Server may still be starting (waited {max_wait_time}s)')
			return process
		
		return process
		
	except Exception as e:
		print(f'❌ Failed to start Browser Action Server: {e}')
		return None


def stop_server(host: str = '127.0.0.1', port: int = 8766) -> bool:
	"""
	Stop the Browser Action Server.
	
	Args:
		host: Server host
		port: Server port
		
	Returns:
		True if server was stopped or wasn't running, False if error
	"""
	try:
		if not is_server_running(host, port):
			print('✅ Browser Action Server is not running')
			return True
		
		# Try to gracefully stop via API (if we add a shutdown endpoint)
		# For now, we'll need to kill the process
		print('⚠️ Server shutdown via API not implemented yet')
		print('   Kill the server process manually if needed')
		return True
		
	except Exception as e:
		print(f'❌ Error stopping server: {e}')
		return False


def get_server_status(host: str = '127.0.0.1', port: int = 8766) -> dict[str, Any] | None:
	"""
	Get current server status information.
	
	Args:
		host: Server host
		port: Server port
		
	Returns:
		Server status data if running, None if not running
	"""
	try:
		with httpx.Client(timeout=5.0) as client:
			response = client.get(f'http://{host}:{port}/health')
			if response.status_code == 200:
				return response.json()
			return None
	except Exception:
		return None


async def send_action(
	endpoint: str,
	data: dict[str, Any] | None = None,
	host: str = '127.0.0.1',
	port: int = 8766,
	timeout: float = 30.0
) -> dict[str, Any] | None:
	"""
	Send action command to Browser Action Server.
	
	Convenience function for Claude Code to send actions easily.
	
	Args:
		endpoint: API endpoint (e.g., 'navigate', 'click', 'type')
		data: Request data (if POST request)
		host: Server host
		port: Server port
		timeout: Request timeout
		
	Returns:
		Response data if successful, None if failed
	"""
	try:
		url = f'http://{host}:{port}/{endpoint.lstrip("/")}'
		
		async with httpx.AsyncClient(timeout=timeout) as client:
			if data is not None:
				response = await client.post(url, json=data)
			else:
				response = await client.get(url)
			
			if response.status_code == 200:
				return response.json()
			else:
				print(f'❌ Action failed: {response.status_code} - {response.text}')
				return None
				
	except Exception as e:
		print(f'❌ Error sending action: {e}')
		return None


# Convenience functions for common actions

async def navigate(url: str, **kwargs) -> dict[str, Any] | None:
	"""Navigate to URL"""
	# Extract connection parameters
	host = kwargs.pop('host', '127.0.0.1')
	port = kwargs.pop('port', 8766)
	timeout = kwargs.pop('timeout', 30.0)
	
	return await send_action('navigate', {'url': url, 'timeout': timeout, **kwargs}, host=host, port=port, timeout=timeout)


async def click(selector: str, **kwargs) -> dict[str, Any] | None:
	"""Click element"""
	host = kwargs.pop('host', '127.0.0.1')
	port = kwargs.pop('port', 8766)
	timeout = kwargs.pop('timeout', 30.0)
	
	return await send_action('click', {'selector': selector, 'timeout': timeout, **kwargs}, host=host, port=port, timeout=timeout)


async def type_text(selector: str, text: str, **kwargs) -> dict[str, Any] | None:
	"""Type text into element"""
	host = kwargs.pop('host', '127.0.0.1')
	port = kwargs.pop('port', 8766)
	timeout = kwargs.pop('timeout', 30.0)
	
	return await send_action('type', {'selector': selector, 'text': text, 'timeout': timeout, **kwargs}, host=host, port=port, timeout=timeout)


async def scroll(direction: str, amount: int = 300, **kwargs) -> dict[str, Any] | None:
	"""Scroll page"""
	host = kwargs.pop('host', '127.0.0.1')
	port = kwargs.pop('port', 8766)
	timeout = kwargs.pop('timeout', 30.0)
	
	return await send_action('scroll', {'direction': direction, 'amount': amount, 'timeout': timeout, **kwargs}, host=host, port=port, timeout=timeout)


async def take_screenshot(**kwargs) -> dict[str, Any] | None:
	"""Take screenshot"""
	host = kwargs.pop('host', '127.0.0.1')
	port = kwargs.pop('port', 8766)
	timeout = kwargs.pop('timeout', 30.0)
	
	return await send_action('screenshot', None, host=host, port=port, timeout=timeout)


async def get_page_status(**kwargs) -> dict[str, Any] | None:
	"""Get page status"""
	host = kwargs.pop('host', '127.0.0.1')
	port = kwargs.pop('port', 8766)
	timeout = kwargs.pop('timeout', 30.0)
	
	return await send_action('status', None, host=host, port=port, timeout=timeout)


async def wait_for_element(selector: str, timeout: float = 10.0, **kwargs) -> dict[str, Any] | None:
	"""Wait for element to appear"""
	host = kwargs.pop('host', '127.0.0.1')
	port = kwargs.pop('port', 8766)
	request_timeout = kwargs.pop('request_timeout', 30.0)
	
	return await send_action('wait', {
		'condition_type': 'element',
		'selector': selector,
		'timeout': timeout,
		**kwargs
	}, host=host, port=port, timeout=request_timeout)


# Auto-start helper for Claude Code

def ensure_server_running(
	host: str = '127.0.0.1',
	port: int = 8766,
	debug: bool = False,
	auto_start: bool = True
) -> bool:
	"""
	Ensure Browser Action Server is running.
	
	Auto-starts if not running and auto_start=True.
	Perfect for Claude Code to call at the start of automation tasks.
	
	Args:
		host: Server host
		port: Server port
		debug: Enable debug logging
		auto_start: Automatically start server if not running
		
	Returns:
		True if server is running, False otherwise
	"""
	if is_server_running(host, port):
		print(f'✅ Browser Action Server is running on {host}:{port}')
		return True
	
	if auto_start:
		print(f'🚀 Starting Browser Action Server...')
		process = start_server_background(host, port, debug)
		return process is not None
	else:
		print(f'❌ Browser Action Server is not running on {host}:{port}')
		return False


if __name__ == '__main__':
	"""CLI entry point for server management"""
	import argparse
	
	parser = argparse.ArgumentParser(description='Browser Action Server launcher')
	parser.add_argument('--host', default='127.0.0.1', help='Server host')
	parser.add_argument('--port', type=int, default=8766, help='Server port')
	parser.add_argument('--debug', action='store_true', help='Enable debug logging')
	
	subparsers = parser.add_subparsers(dest='command', help='Commands')
	
	subparsers.add_parser('start', help='Start server')
	subparsers.add_parser('stop', help='Stop server')
	subparsers.add_parser('status', help='Get server status')
	subparsers.add_parser('ensure', help='Ensure server is running')
	
	args = parser.parse_args()
	
	if args.command == 'start':
		start_server_background(args.host, args.port, args.debug)
	elif args.command == 'stop':
		stop_server(args.host, args.port)
	elif args.command == 'status':
		status = get_server_status(args.host, args.port)
		if status:
			print(f'Server status: {status}')
		else:
			print('Server is not running')
	elif args.command == 'ensure':
		ensure_server_running(args.host, args.port, args.debug)
	else:
		print('Use --help for available commands')