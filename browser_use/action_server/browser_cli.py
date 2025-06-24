#!/usr/bin/env python3
"""
Browser Action CLI Tool

Simple command-line interface for Claude Code to send browser actions
without writing Python code each time.

Usage:
    browser-action navigate https://example.com
    browser-action click "#button"
    browser-action type "#input" "Hello World"
    browser-action screenshot
    browser-action status
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add browser_use to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from browser_use.action_server.launcher import (
	click,
	ensure_server_running,
	get_page_status,
	navigate,
	scroll,
	take_screenshot,
	type_text,
	wait_for_element,
)


def print_result(result, action_name):
	"""Print action result in a nice format"""
	if result is None:
		print(f'❌ {action_name} failed: No response')
		return False

	if result.get('success'):
		print(f'✅ {action_name} succeeded')

		# Print specific data based on action
		data = result.get('data', {})
		if 'url' in data and 'title' in data:
			print(f'   Page: {data["title"]} ({data["url"]})')
		elif 'current_value' in data:
			print(f'   Value: {data["current_value"]}')
		elif 'element' in data:
			elem = data['element']
			print(f'   Element: {elem.get("tagName", "Unknown")}')
		elif 'size_bytes' in data:
			print(f'   Screenshot: {data["size_bytes"]} bytes')
		elif 'element_count' in data:
			print(f'   Elements: {data["element_count"]}, Ready: {data.get("ready_state", "Unknown")}')

		exec_time = result.get('execution_time_ms', 0)
		print(f'   Time: {exec_time:.1f}ms')
		return True
	else:
		error = result.get('error', {})
		print(f'❌ {action_name} failed: {error.get("type", "Unknown error")}')
		print(f'   Message: {error.get("message", "No details")}')
		return False


async def cmd_navigate(args):
	"""Navigate to URL"""
	result = await navigate(args.url, host=args.host, port=args.port, timeout=args.timeout)
	return print_result(result, f'Navigate to {args.url}')


async def cmd_click(args):
	"""Click element"""
	result = await click(args.selector, host=args.host, port=args.port, timeout=args.timeout)
	return print_result(result, f'Click {args.selector}')


async def cmd_type(args):
	"""Type text into element"""
	result = await type_text(args.selector, args.text, host=args.host, port=args.port, timeout=args.timeout)
	return print_result(result, f'Type into {args.selector}')


async def cmd_scroll(args):
	"""Scroll page"""
	result = await scroll(args.direction, args.amount, host=args.host, port=args.port, timeout=args.timeout)
	return print_result(result, f'Scroll {args.direction} {args.amount}px')


async def cmd_screenshot(args):
	"""Take screenshot"""
	result = await take_screenshot(host=args.host, port=args.port, timeout=args.timeout)
	return print_result(result, 'Screenshot')


async def cmd_status(args):
	"""Get page status"""
	result = await get_page_status(host=args.host, port=args.port, timeout=args.timeout)
	return print_result(result, 'Page status')


async def cmd_wait(args):
	"""Wait for element"""
	result = await wait_for_element(args.selector, timeout=args.wait_time, host=args.host, port=args.port)
	return print_result(result, f'Wait for {args.selector}')


async def cmd_server(args):
	"""Start/check server"""
	if args.action == 'start':
		success = ensure_server_running(host=args.host, port=args.port, debug=args.debug, auto_start=True)
		if success:
			print(f'✅ Browser Action Server running on {args.host}:{args.port}')
		else:
			print('❌ Failed to start server')
		return success
	elif args.action == 'status':
		from browser_use.action_server.launcher import get_server_status

		status = get_server_status(args.host, args.port)
		if status:
			print('✅ Server is running:')
			print(f'   Status: {status["data"]["status"]}')
			print(f'   Version: {status["data"]["version"]}')
			print(f'   Browser: {"Connected" if status["data"]["browser_connected"] else "Not connected"}')
			print(f'   Uptime: {status["data"]["uptime_seconds"]:.1f}s')
			print(f'   Requests: {status["data"]["total_requests"]}')
			return True
		else:
			print(f'❌ Server not running on {args.host}:{args.port}')
			return False


def main():
	"""Main CLI entry point"""
	parser = argparse.ArgumentParser(
		description='Browser Action CLI - Control browsers from Claude Code',
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog="""
Examples:
  browser-action server start                    # Start the server
  browser-action navigate https://example.com   # Navigate to URL
  browser-action click "#submit-btn"            # Click element
  browser-action type "#search" "hello world"   # Type text
  browser-action scroll down 300                # Scroll page
  browser-action screenshot                      # Take screenshot
  browser-action status                          # Get page info
  browser-action wait "#loading" 10             # Wait for element
		""",
	)

	# Global options
	parser.add_argument('--host', default='127.0.0.1', help='Server host')
	parser.add_argument('--port', type=int, default=8766, help='Server port')
	parser.add_argument('--timeout', type=float, default=10.0, help='Action timeout')
	parser.add_argument('--debug', action='store_true', help='Enable debug mode')

	# Subcommands
	subparsers = parser.add_subparsers(dest='command', help='Available commands')

	# Server commands
	server_parser = subparsers.add_parser('server', help='Server management')
	server_parser.add_argument('action', choices=['start', 'status'], help='Server action')
	server_parser.set_defaults(func=cmd_server)

	# Navigate command
	nav_parser = subparsers.add_parser('navigate', help='Navigate to URL')
	nav_parser.add_argument('url', help='URL to navigate to')
	nav_parser.set_defaults(func=cmd_navigate)

	# Click command
	click_parser = subparsers.add_parser('click', help='Click element')
	click_parser.add_argument('selector', help='CSS selector of element to click')
	click_parser.set_defaults(func=cmd_click)

	# Type command
	type_parser = subparsers.add_parser('type', help='Type text into element')
	type_parser.add_argument('selector', help='CSS selector of input element')
	type_parser.add_argument('text', help='Text to type')
	type_parser.set_defaults(func=cmd_type)

	# Scroll command
	scroll_parser = subparsers.add_parser('scroll', help='Scroll page')
	scroll_parser.add_argument('direction', choices=['up', 'down', 'left', 'right'], help='Scroll direction')
	scroll_parser.add_argument('amount', type=int, nargs='?', default=300, help='Pixels to scroll')
	scroll_parser.set_defaults(func=cmd_scroll)

	# Screenshot command
	screenshot_parser = subparsers.add_parser('screenshot', help='Take page screenshot')
	screenshot_parser.set_defaults(func=cmd_screenshot)

	# Status command
	status_parser = subparsers.add_parser('status', help='Get current page status')
	status_parser.set_defaults(func=cmd_status)

	# Wait command
	wait_parser = subparsers.add_parser('wait', help='Wait for element to appear')
	wait_parser.add_argument('selector', help='CSS selector to wait for')
	wait_parser.add_argument('wait_time', type=float, nargs='?', default=10.0, help='Seconds to wait')
	wait_parser.set_defaults(func=cmd_wait)

	# Parse arguments
	args = parser.parse_args()

	if not args.command:
		parser.print_help()
		return 1

	# Run the command
	try:
		success = asyncio.run(args.func(args))
		return 0 if success else 1
	except KeyboardInterrupt:
		print('\n⚠️ Interrupted')
		return 1
	except Exception as e:
		print(f'❌ Error: {e}')
		return 1


if __name__ == '__main__':
	sys.exit(main())
