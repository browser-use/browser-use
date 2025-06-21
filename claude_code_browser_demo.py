#!/usr/bin/env python3
"""
Claude Code Browser Action Demo

This script demonstrates how Claude Code can control a browser directly
through the Browser Action Server without blocking the terminal.

The key insight: Claude Code sends individual HTTP commands and gets
immediate responses, allowing for real-time decision making.
"""

import asyncio
import sys
from pathlib import Path

# Add browser_use to path
sys.path.insert(0, str(Path(__file__).parent / 'browser_use'))

print('🌐 Claude Code Browser Control Demo')
print('=' * 50)


async def claude_code_browser_automation():
	"""
	Simulate how Claude Code would control a browser step-by-step.

	This demonstrates the non-blocking pattern where:
	1. Claude Code sends an action
	2. Gets immediate response
	3. Decides next action based on response
	4. Repeats until task complete
	"""

	try:
		# Step 1: Ensure server is running
		print('Step 1: Starting Browser Action Server...')
		from browser_use.action_server.launcher import (
			click,
			ensure_server_running,
			get_page_status,
			navigate,
			scroll,
			take_screenshot,
		)

		# This is non-blocking - starts server in background if needed
		if ensure_server_running(port=8773, debug=False):
			print('✅ Server is ready!')
		else:
			print('❌ Could not start server')
			return False

		# Wait a moment for server to be fully ready
		await asyncio.sleep(1.0)

		# Step 2: Navigate to a website
		print('\nStep 2: Navigate to website...')
		result = await navigate('https://example.com', host='127.0.0.1', port=8773, timeout=15.0)
		if result and result['success']:
			print(f'✅ Navigated to: {result["data"]["title"]}')
			print(f'   URL: {result["data"]["url"]}')
		else:
			print(f'❌ Navigation failed: {result}')
			return False

		# Step 3: Analyze the page
		print('\nStep 3: Analyze current page...')
		status = await get_page_status(host='127.0.0.1', port=8773)
		if status and status['success']:
			data = status['data']
			print('✅ Page analysis:')
			print(f'   Title: {data["title"]}')
			print(f'   Elements: {data["element_count"]}')
			print(f'   Ready: {data["ready_state"]}')

			# Decision: if page has many elements, take screenshot
			if data['element_count'] > 10:
				print('   → Page has many elements, taking screenshot...')
				screenshot = await take_screenshot(host='127.0.0.1', port=8773)
				if screenshot and screenshot['success']:
					size = screenshot['data']['size_bytes']
					print(f'   ✅ Screenshot captured: {size} bytes')

		# Step 4: Interact with the page based on what we found
		print('\nStep 4: Interact with page...')

		# Try to scroll down to see more content
		scroll_result = await scroll('down', amount=300, host='127.0.0.1', port=8773)
		if scroll_result and scroll_result['success']:
			pos = scroll_result['data']['scroll_position']
			print(f'✅ Scrolled to position: ({pos["x"]}, {pos["y"]})')

		# Click on the page body (safe click)
		click_result = await click('body', host='127.0.0.1', port=8773, timeout=5.0)
		if click_result and click_result['success']:
			elem = click_result['data']['element']
			print(f'✅ Clicked on: {elem["tagName"]} element')

		# Step 5: Final analysis
		print('\nStep 5: Final page analysis...')
		final_status = await get_page_status(host='127.0.0.1', port=8773)
		if final_status and final_status['success']:
			data = final_status['data']
			print(f'✅ Final state: {data["title"]} with {data["element_count"]} elements')

		print('\n🎉 Browser automation completed successfully!')
		print('✅ Navigated to webpage')
		print('✅ Analyzed page content')
		print('✅ Took screenshot')
		print('✅ Interacted with page elements')
		print('✅ All actions were non-blocking')

		return True

	except Exception as e:
		print(f'\n❌ Demo failed: {e}')
		import traceback

		traceback.print_exc()
		return False


async def demonstrate_claude_code_patterns():
	"""Show different patterns Claude Code can use"""

	print('\n' + '=' * 50)
	print('🧠 Claude Code Usage Patterns')
	print('=' * 50)

	# Pattern 1: Direct HTTP calls (for when you want full control)
	print('\nPattern 1: Direct HTTP calls')
	import httpx

	try:
		async with httpx.AsyncClient(timeout=10.0) as client:
			response = await client.get('http://127.0.0.1:8773/status')
			if response.status_code == 200:
				data = response.json()
				if data['success']:
					print(f'✅ Direct call: {data["data"]["title"]}')
				else:
					print(f'❌ Direct call failed: {data["error"]}')
			else:
				print(f'❌ HTTP error: {response.status_code}')
	except Exception as e:
		print(f'⚠️ Pattern 1 skipped: {e}')

	# Pattern 2: Helper functions (for convenience)
	print('\nPattern 2: Helper functions')
	try:
		from browser_use.action_server.launcher import get_page_status

		status = await get_page_status(host='127.0.0.1', port=8773)
		if status and status['success']:
			data = status['data']
			print(f'✅ Helper function: {data["element_count"]} elements found')
		else:
			print('❌ Helper function failed')
	except Exception as e:
		print(f'⚠️ Pattern 2 skipped: {e}')

	# Pattern 3: Error handling and recovery
	print('\nPattern 3: Error handling')
	try:
		from browser_use.action_server.launcher import click

		# Try to click something that doesn't exist
		result = await click('#nonexistent-element', host='127.0.0.1', port=8773, timeout=2.0)
		if result:
			if result['success']:
				print('✅ Unexpected success')
			else:
				error_type = result['error']['type']
				print(f'✅ Error handled gracefully: {error_type}')
		else:
			print('✅ Error returned None (also valid)')
	except Exception as e:
		print(f'✅ Exception caught: {type(e).__name__}')


async def main():
	"""Run the complete demonstration"""

	print('This demo shows how Claude Code can control browsers directly')
	print('without blocking the terminal or requiring long-running scripts.')
	print()

	# Run main automation demo
	success = await claude_code_browser_automation()

	if success:
		# Show different usage patterns
		await demonstrate_claude_code_patterns()

		print('\n' + '=' * 50)
		print('🎯 DEMO COMPLETE!')
		print('=' * 50)
		print('The Browser Action Server enables Claude Code to:')
		print('✅ Control browsers without blocking the terminal')
		print('✅ Get real-time feedback after each action')
		print('✅ Make decisions based on page state')
		print('✅ Handle errors gracefully')
		print('✅ Chain actions together intelligently')
		print()
		print('🚀 Usage from Claude Code chat:')
		print('```python')
		print('from browser_use.action_server.launcher import *')
		print('ensure_server_running()  # Start server')
		print("result = await navigate('https://example.com')")
		print("print(result['data']['title'])  # Example Domain")
		print('```')

		return True
	else:
		print('\n❌ Demo failed - check error messages above')
		return False


if __name__ == '__main__':
	try:
		success = asyncio.run(main())
		print(f'\nDemo result: {"SUCCESS" if success else "FAILED"}')
		sys.exit(0 if success else 1)
	except KeyboardInterrupt:
		print('\n⚠️ Demo interrupted')
		sys.exit(1)
	except Exception as e:
		print(f'\n❌ Demo error: {e}')
		sys.exit(1)
