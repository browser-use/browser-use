"""
Direct Captcha Solver for Local Server

This script uses a simpler approach to solve the tap and hold captcha.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.browser import BrowserConfig
from browser_use.controller.service import Controller
from browser_use.llm import ChatOpenAI


async def solve_captcha_direct():
	"""Direct approach to solve the captcha"""

	print('🎯 Direct captcha solver starting...')

	# Create a simple agent with basic actions
	agent = Agent(
		task="""
        Go to https://browser-use.github.io/stress-tests/tap-hold-captcha.html and solve the captcha
        """,
		llm=ChatOpenAI(model='gpt-4o'),
		browser_config=BrowserConfig(headless=False),
	)

	try:
		print('🤖 Starting direct solve attempt...')
		result = await agent.run()
		print('✅ Direct solve completed!')
		return result

	except Exception as e:
		print(f'❌ Direct solve failed: {e}')
		return None


async def solve_captcha_with_manual_hold():
	"""Try solving with manual mouse actions"""

	print('🎯 Manual mouse action approach...')

	# Create controller and add a manual mouse hold action
	controller = Controller()

	@controller.action('Manual mouse hold on coordinates for specified seconds')
	async def manual_mouse_hold(x: int, y: int, hold_seconds: float, browser_session):
		"""Manually control mouse to hold at specific coordinates"""
		try:
			page = await browser_session.get_current_page()

			print(f'🎯 Moving to coordinates ({x}, {y})')
			await page.mouse.move(x, y)

			print('⬇️ Mouse down')
			await page.mouse.down()

			print(f'⏱️ Holding for {hold_seconds} seconds...')
			await asyncio.sleep(hold_seconds)

			print('⬆️ Mouse up')
			await page.mouse.up()

			await asyncio.sleep(1)  # Wait for verification

			return f'Held mouse at ({x}, {y}) for {hold_seconds}s'

		except Exception as e:
			return f'Manual hold failed: {str(e)}'

	agent = Agent(
		task="""
        Go to http://[::]:8005/tap-hold-captcha.html and solve the captcha:
        
        1. Navigate to the URL
        2. Take a screenshot to see the current state
        3. Find the 'HOLD ME' button coordinates (it should be visible)
        4. Use manual_mouse_hold with the approximate coordinates (like x=400, y=300) for 4 seconds
        5. Check if captcha is solved
        6. If not, try different coordinates or longer duration
        """,
		llm=ChatOpenAI(model='gpt-4o'),
		controller=controller,
		browser_config=BrowserConfig(headless=False),
	)

	try:
		print('🤖 Starting manual mouse approach...')
		result = await agent.run()
		print('✅ Manual approach completed!')
		return result

	except Exception as e:
		print(f'❌ Manual approach failed: {e}')
		return None


async def main():
	"""Try multiple approaches to solve the captcha"""

	print('=' * 60)
	print('🔐 DIRECT CAPTCHA SOLVER')
	print('=' * 60)
	print('Target: http://[::]:8005/tap-hold-captcha.html')
	print()

	# Try approach 1: Direct simple method
	print('🚀 Trying Approach 1: Direct clicking method...')
	result1 = await solve_captcha_direct()

	if result1:
		print('✅ Direct method succeeded!')
		return

	print('\n' + '=' * 40)
	print('🚀 Trying Approach 2: Manual mouse control...')
	result2 = await solve_captcha_with_manual_hold()

	if result2:
		print('✅ Manual method succeeded!')
		return

	print('\n❌ Both approaches completed. Check browser for results.')


if __name__ == '__main__':
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		print('\n👋 Interrupted by user')
	except Exception as e:
		print(f'\n❌ Error: {e}')
	finally:
		input('\nPress Enter to exit...')
