"""Play 2048 game using Expectimax solver instead of LLM reasoning."""

import asyncio

from browser_use import Agent, Browser, ChatOpenAI, ChatGoogle
from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.llm.browser_use.chat import ChatBrowserUse
from browser_use.tools.service import Tools
from game_2048_solver import Game2048Solver
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


async def main():
	"""Run the 2048 game agent"""
	browser = Browser(headless=False, use_cloud=False, cross_origin_iframes=False, highlight_elements=True)
	llm = ChatBrowserUse()

	task = """Play 2048 at http://play2048.co and reach the 2048 tile.

SETUP:
1. Navigate to http://play2048.co
2. A "WELCOME TO 2048!" popup will appear with tutorial buttons. DO NOT click tutorial buttons (1, 2, 3) or "Play Tutorial".
3. Close the popup by clicking ONLY the X button in the top-right corner of the popup.
4. If ANY other ads or popups appear covering the game board, close them immediately by clicking their X or close buttons.
5. Wait 1 second for the game board to be fully visible and clear of popups.
6. Verify the 4x4 game board is visible before starting gameplay.

GAMEPLAY:
Use get_2048_move and send_keys in alternation:

1. Call get_2048_move → Returns "ArrowLeft" (or ArrowRight/Up/Down)
2. Call send_keys with keys="ArrowLeft" → Executes the move
3. Call get_2048_move → Returns next move
4. Call send_keys with the new move
... repeat until you win ...

IMPORTANT: ALWAYS alternate between get_2048_move and send_keys. Never call get_2048_move twice in a row. NEVER FORGET THIS. DOUBLE CHECK ON EVERY TURN. Never execute code as well.

HANDLING ADS DURING GAMEPLAY:
If get_2048_move returns "Ad or popup detected" error:
1. Look for any overlay, modal, or popup covering the game board
2. Find and click the X button, close button, or "No thanks" button on the ad
3. Wait 1 second for the ad to close
4. Resume the get_2048_move → send_keys alternation

WINNING:
If and only if get_2048_move returns "Successfully reached the 2048 tile!", use done with success=true. NEVER RETURN EARLY. YOU MUST ACHIEVE THE TILE. DOUBLE CHECK BEFORE RETURNING.

"""

	# Create custom tools with the solver action
	# Search depth: 3=fast/decent, 4=balanced/good, 5=slow/excellent
	# Depth 4 should reach 2048 ~70-90% of the time
	solver = Game2048Solver(search_depth=4)

	# Track previous board state to detect when agent is stuck
	previous_board = None
	duplicate_count = 0

	tools = Tools()

	async def _extract_board_with_vision(browser_session: BrowserSession) -> list[list[int]] | ActionResult:
		"""
		Extract the 2048 board state using vision analysis.

		Returns:
			Board as 4x4 list of ints, or ActionResult if error occurred
		"""
		import json
		import re

		from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL, UserMessage

		cdp_session = await browser_session.get_or_create_cdp_session()

		# Take screenshot of current viewport
		screenshot_result = await cdp_session.cdp_client.send.Page.captureScreenshot(
			params={'format': 'png', 'captureBeyondViewport': False}, session_id=cdp_session.session_id
		)

		screenshot_data = screenshot_result.get('data')
		if not screenshot_data:
			print('⚠️  Failed to capture screenshot')
			return ActionResult(error='Failed to capture screenshot')

		# Ask LLM to extract board state from screenshot
		vision_prompt = """Extract the 2048 board from this screenshot.

If ads/popups block the board: respond "AD_DETECTED"

Otherwise return board as JSON (0=empty, numbers=tiles):
[[r1c1, r1c2, r1c3, r1c4],
 [r2c1, r2c2, r2c3, r2c4],
 [r3c1, r3c2, r3c3, r3c4],
 [r4c1, r4c2, r4c3, r4c4]]

Example:
[[2, 0, 0, 4],
 [0, 8, 0, 0],
 [0, 0, 16, 0],
 [0, 0, 0, 2]]"""

		# Create message with screenshot
		user_message = UserMessage(
			content=[
				ContentPartTextParam(type='text', text=vision_prompt),
				ContentPartImageParam(
					type='image_url',
					image_url=ImageURL(url=f'data:image/png;base64,{screenshot_data}', media_type='image/png'),
				),
			]
		)

		# Get LLM to analyze the screenshot with retry logic
		llm_instance = llm
		max_retries = 3
		retry_delay = 2.0  # Increased from 1.0 to reduce API errors

		for attempt in range(max_retries):
			try:
				response = await llm_instance.ainvoke([user_message])
				break  # Success, exit retry loop
			except Exception as e:
				if attempt < max_retries - 1:
					print(f'⚠️  Vision analysis failed (attempt {attempt + 1}/{max_retries}): {e}')
					print(f'⚠️  Retrying in {retry_delay}s...')
					await asyncio.sleep(retry_delay)
					retry_delay *= 2  # Exponential backoff (2s → 4s → 8s)
				else:
					print(f'⚠️  Vision analysis failed after {max_retries} attempts')
					return ActionResult(error=f'Failed to analyze board after {max_retries} attempts: {e}')

		# Add delay after successful vision call to prevent API overload
		await asyncio.sleep(2.0)

		# Parse the board from LLM response
		board_text = response.completion.strip()

		# Check if ad/popup is detected
		if 'AD_DETECTED' in board_text:
			print('⚠️  Ad or popup detected covering the game board')
			return ActionResult(error='Ad or popup detected - please close it by clicking X or close buttons')

		# Try to extract JSON array from response
		json_match = re.search(r'\[\s*\[.*?\]\s*\]', board_text, re.DOTALL)
		if not json_match:
			print(f'⚠️  Could not find board JSON in LLM response: {board_text[:200]}')
			return ActionResult(error='Failed to parse board from screenshot')

		try:
			board = json.loads(json_match.group(0))
		except json.JSONDecodeError as e:
			print(f'⚠️  Invalid JSON in LLM response: {e}')
			return ActionResult(error='Failed to parse board JSON')

		# Validate board structure
		if not isinstance(board, list) or len(board) != 4:
			print(
				f'⚠️  Invalid board structure: expected 4 rows, got {len(board) if isinstance(board, list) else "not a list"}'
			)
			return ActionResult(error='Invalid board structure')

		for i, row in enumerate(board):
			if not isinstance(row, list) or len(row) != 4:
				print(f'⚠️  Invalid row {i}: expected 4 columns, got {len(row) if isinstance(row, list) else "not a list"}')
				return ActionResult(error=f'Invalid board row {i}')

		# Check if board is empty
		has_tiles = any(cell != 0 for row in board for cell in row)
		if not has_tiles:
			print('⚠️  Board appears to be empty')
			return ActionResult(error='Game board appears empty - wait for game to start')

		return board

	@tools.action('Analyzes the 2048 board using vision and returns the optimal move direction')
	async def get_2048_move(browser_session: BrowserSession) -> ActionResult:
		"""
		Extract board state and calculate optimal move.

		Returns:
			ActionResult with the optimal arrow key direction to press
		"""
		# PHASE 1: Extract board state using vision
		board = await _extract_board_with_vision(browser_session)
		if isinstance(board, ActionResult):  # Error occurred
			return board

		# Check for duplicate board state (agent stuck not executing moves)
		nonlocal previous_board, duplicate_count

		if previous_board is not None and board == previous_board:
			duplicate_count += 1
			print(f'⚠️  DUPLICATE BOARD DETECTED (count: {duplicate_count})')
			print('⚠️  The board has not changed since the last call!')

			if duplicate_count >= 2:
				print('⚠️  STUCK! You called get_2048_move multiple times without executing send_keys!')
				return ActionResult(
					error='CRITICAL: You called get_2048_move multiple times but the board did not change. Your NEXT action MUST be send_keys with the arrow key from the previous result. Stop calling get_2048_move!'
				)
		else:
			# Board changed, reset duplicate count
			duplicate_count = 0
			previous_board = [row[:] for row in board]  # Deep copy

		# Check if we've reached 2048
		max_tile = max(max(row) for row in board)
		if max_tile >= 2048:
			print('🎉 SUCCESS! Found 2048 tile on the board!')
			print('\n' + '=' * 50)
			print('📊 FINAL BOARD STATE:')
			print('=' * 50)
			for i, row in enumerate(board):
				row_str = '│ '
				for val in row:
					if val == 0:
						row_str += '    . '
					else:
						row_str += f'{val:5d} '
				row_str += '│'
				print(row_str)
				if i < 3:
					print('├' + '─' * 42 + '┤')
			print('=' * 50 + '\n')
			return ActionResult(
				extracted_content='Successfully reached the 2048 tile! Use done action with success=true to complete the task.',
				is_done=False,
			)

		# PHASE 2: Use Expectimax solver to get best move
		best_move = solver.get_best_move(board)

		# Display board state in a nice formatted grid
		print('\n' + '=' * 50)
		print('📊 CURRENT BOARD STATE:')
		print('=' * 50)

		# Create formatted board display
		for i, row in enumerate(board):
			row_str = '│ '
			for val in row:
				if val == 0:
					row_str += '    . '
				else:
					row_str += f'{val:5d} '
			row_str += '│'
			print(row_str)
			if i < 3:
				print('├' + '─' * 42 + '┤')

		print('=' * 50)
		print(f'🎯 Best move: {best_move}')
		print('=' * 50 + '\n')

		# Return the move direction
		return ActionResult(
			extracted_content=f'{best_move}. IMPORTANT: Your next action MUST be send_keys with keys="{best_move}". Do not call get_2048_move again until you have executed this move.'
		)

	# Create agent with custom tools
	agent = Agent(
		task=task,
		llm=llm,
		browser=browser,
		tools=tools,
		use_vision=True,
	)

	print('🎮 Starting 2048 agent with Expectimax solver...')
	print('🎯 Goal: Reach the 2048 tile')
	print('🧠 Strategy: Expectimax search (depth 4) with weighted heuristics')
	print('📈 Heuristics: Empty tiles, Monotonicity, Smoothness, Max tile, Corner position')
	print('⚡ Expected win rate: ~70-90% for 2048 tile')
	print('📊 Max steps: UNLIMITED (will run until 2048 is reached or game over)')
	print('⏱️  Time limit: NONE (may take several hours)')
	print()

	try:
		result = await agent.run(max_steps=999999)  # Effectively unlimited

		print()
		print('=' * 60)
		if result.is_done():
			print('✅ SUCCESS! Agent completed the task!')
		else:
			print('❌ Agent did not complete the task')
		print('=' * 60)

	except KeyboardInterrupt:
		print('\n\n⚠️  Interrupted by user')
	except Exception as e:
		print(f'\n\n❌ Error: {e}')
		import traceback

		traceback.print_exc()
	finally:
		# Cleanup
		print('\n🧹 Cleaning up...')
		try:
			await asyncio.sleep(1.0)
			browser_session = agent.browser_session
			await browser_session.event_bus.stop(clear=True, timeout=2)
			await browser_session.kill()
			print('✨ Cleanup complete')
		except Exception as e:
			print(f'⚠️  Cleanup error: {e}')


if __name__ == '__main__':
	asyncio.run(main())
