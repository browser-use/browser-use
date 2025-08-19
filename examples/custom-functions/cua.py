"""
OpenAI Computer Use Assistant (CUA) Integration

This example demonstrates how to integrate OpenAI's Computer Use Assistant as a fallback
action when standard browser actions are insufficient to achieve the desired goal.
The CUA can perform complex computer interactions that might be difficult to achieve
through regular browser-use actions.
"""

import asyncio
import base64
import os
import sys
from io import BytesIO

from PIL import Image

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from browser_use import Agent, ChatOpenAI, Controller
from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession

try:
	from lmnr import Laminar

	Laminar.initialize(project_api_key=os.getenv('LMNR_PROJECT_API_KEY'))
except ImportError:
	pass


class OpenAICUAAction(BaseModel):
	"""Parameters for OpenAI Computer Use Assistant action."""

	description: str = Field(..., description='Description of your next goal')


async def handle_model_action(browser_session: BrowserSession, action) -> ActionResult:
	"""
	Given a computer action (e.g., click, double_click, scroll, etc.),
	execute the corresponding operation using CDP.
	"""
	action_type = action.type
	ERROR_MSG: str = 'Could not execute the CUA action.'

	if not browser_session.agent_focus:
		return ActionResult(error='No active browser session')

	try:
		match action_type:
			case 'click':
				x, y = action.x, action.y
				button = action.button
				print(f"Action: click at ({x}, {y}) with button '{button}'")
				# Not handling things like middle click, etc.
				if button != 'left' and button != 'right':
					button = 'left'

				# Use CDP to click
				await browser_session.agent_focus.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mousePressed',
						'x': x,
						'y': y,
						'button': button,
						'clickCount': 1,
					},
					session_id=browser_session.agent_focus.session_id,
				)
				await browser_session.agent_focus.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mouseReleased',
						'x': x,
						'y': y,
						'button': button,
					},
					session_id=browser_session.agent_focus.session_id,
				)
				msg = f'Clicked at ({x}, {y}) with button {button}'
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'scroll':
				x, y = action.x, action.y
				scroll_x, scroll_y = action.scroll_x, action.scroll_y
				print(f'Action: scroll at ({x}, {y}) with offsets (scroll_x={scroll_x}, scroll_y={scroll_y})')

				# Move mouse to position first
				await browser_session.agent_focus.cdp_client.send.Input.dispatchMouseEvent(
					params={
						'type': 'mouseMoved',
						'x': x,
						'y': y,
					},
					session_id=browser_session.agent_focus.session_id,
				)

				# Execute scroll using JavaScript
				await browser_session.agent_focus.cdp_client.send.Runtime.evaluate(
					params={
						'expression': f'window.scrollBy({scroll_x}, {scroll_y})',
					},
					session_id=browser_session.agent_focus.session_id,
				)
				msg = f'Scrolled at ({x}, {y}) with offsets (scroll_x={scroll_x}, scroll_y={scroll_y})'
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'keypress':
				keys = action.keys
				for k in keys:
					print(f"Action: keypress '{k}'")
					# A simple mapping for common keys; expand as needed.
					key_code = k
					if k.lower() == 'enter':
						key_code = 'Enter'
					elif k.lower() == 'space':
						key_code = 'Space'

					# Use CDP to send key
					await browser_session.agent_focus.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyDown',
							'key': key_code,
						},
						session_id=browser_session.agent_focus.session_id,
					)
					await browser_session.agent_focus.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'keyUp',
							'key': key_code,
						},
						session_id=browser_session.agent_focus.session_id,
					)
				msg = f'Pressed keys: {keys}'
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'type':
				text = action.text
				print(f'Action: type text: {text}')

				# Type text character by character
				for char in text:
					await browser_session.agent_focus.cdp_client.send.Input.dispatchKeyEvent(
						params={
							'type': 'char',
							'text': char,
						},
						session_id=browser_session.agent_focus.session_id,
					)
				msg = f'Typed text: {text}'
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'wait':
				print('Action: wait')
				await asyncio.sleep(2)
				msg = 'Waited for 2 seconds'
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'screenshot':
				# Nothing to do as screenshot is taken at each turn
				print('Action: screenshot')
				return ActionResult(error=ERROR_MSG)
			# Handle other actions here

			case _:
				print(f'Unrecognized action: {action}')
				return ActionResult(error=ERROR_MSG)

	except Exception as e:
		print(f'Error handling action {action}: {e}')
		return ActionResult(error=ERROR_MSG)


controller = Controller()


@controller.registry.action(
	'Use OpenAI Computer Use Assistant (CUA) as a fallback when standard browser actions cannot achieve the desired goal. This action sends a screenshot and description to OpenAI CUA and executes the returned computer use actions.',
	param_model=OpenAICUAAction,
)
async def openai_cua_fallback(params: OpenAICUAAction, browser_session: BrowserSession):
	"""
	Fallback action that uses OpenAI's Computer Use Assistant to perform complex
	computer interactions when standard browser actions are insufficient.
	"""
	print(f'🎯 CUA Action Starting - Goal: {params.description}')

	try:
		# Get browser state summary
		state = await browser_session.get_browser_state_summary()
		page_info = state.page_info
		if not page_info:
			raise Exception('Page info not found - cannot execute CUA action')

		print(f'📐 Viewport size: {page_info.viewport_width}x{page_info.viewport_height}')

		screenshot_b64 = state.screenshot
		if not screenshot_b64:
			raise Exception('Screenshot not found - cannot execute CUA action')

		print(f'📸 Screenshot captured (base64 length: {len(screenshot_b64)} chars)')

		# Debug: Check screenshot dimensions
		image = Image.open(BytesIO(base64.b64decode(screenshot_b64)))
		print(f'📏 Screenshot actual dimensions: {image.size[0]}x{image.size[1]}')

		# rescale the screenshot to the viewport size
		image = image.resize((page_info.viewport_width, page_info.viewport_height))
		# Save as PNG to bytes buffer
		buffer = BytesIO()
		image.save(buffer, format='PNG')
		buffer.seek(0)
		# Convert to base64
		screenshot_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
		print(f'📸 Rescaled screenshot to viewport size: {page_info.viewport_width}x{page_info.viewport_height}')

		client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
		print('🔄 Sending request to OpenAI CUA...')

		prompt = f"""
        You will be given an action to execute and screenshot of the current screen. 
        Output one computer_call object that will achieve this goal.
        Goal: {params.description}
        """
		response = await client.responses.create(
			model='computer-use-preview',
			tools=[
				{
					'type': 'computer_use_preview',
					'display_width': page_info.viewport_width,
					'display_height': page_info.viewport_height,
					'environment': 'browser',
				}
			],
			input=[
				{
					'role': 'user',
					'content': [
						{'type': 'input_text', 'text': prompt},
						{
							'type': 'input_image',
							'detail': 'auto',
							'image_url': f'data:image/png;base64,{screenshot_b64}',
						},
					],
				}
			],
			truncation='auto',
			temperature=0.1,
		)

		print(f'📥 CUA response received: {response}')
		computer_calls = [item for item in response.output if item.type == 'computer_call']
		computer_call = computer_calls[0] if computer_calls else None
		if not computer_call:
			raise Exception('No computer calls found in CUA response')

		action = computer_call.action
		print(f'🎬 Executing CUA action: {action.type} - {action}')

		action_result = await handle_model_action(browser_session, action)
		await asyncio.sleep(0.1)

		print('✅ CUA action completed successfully')
		return action_result

	except Exception as e:
		msg = f'Error executing CUA action: {e}'
		print(f'❌ {msg}')
		return ActionResult(error=msg)


async def main():
	# Initialize the language model
	llm = ChatOpenAI(
		model='o4-mini',
		temperature=1.0,
	)

	# Create browser session
	browser_session = BrowserSession()

	# Example task that might require CUA fallback
	# This could be a complex interaction that's difficult with standard actions
	task = """
    Go to https://csreis.github.io/tests/cross-site-iframe.html
    Click on "Go cross-site, complex page" using index
    Use the OpenAI CUA fallback to click on "Tree is open..." link.
    """

	# Create agent with our custom controller that includes CUA fallback
	agent = Agent(
		task=task,
		llm=llm,
		controller=controller,
		browser_session=browser_session,
	)

	print('🚀 Starting agent with CUA fallback support...')
	print(f'Task: {task}')
	print('-' * 50)

	try:
		# Run the agent
		result = await agent.run()
		print(f'\n✅ Task completed! Result: {result}')

	except Exception as e:
		print(f'\n❌ Error running agent: {e}')

	finally:
		# Clean up browser session
		await browser_session.kill()
		print('\n🧹 Browser session closed')


if __name__ == '__main__':
	# Example of different scenarios where CUA might be useful

	print('🔧 OpenAI Computer Use Assistant (CUA) Integration Example')
	print('=' * 60)
	print()
	print("This example shows how to integrate OpenAI's CUA as a fallback action")
	print('when standard browser-use actions cannot achieve the desired goal.')
	print()
	print('CUA is particularly useful for:')
	print('• Complex mouse interactions (drag & drop, precise clicking)')
	print('• Keyboard shortcuts and key combinations')
	print('• Actions that require pixel-perfect precision')
	print("• Custom UI elements that don't respond to standard actions")
	print()
	print('Make sure you have OPENAI_API_KEY set in your environment!')
	print()

	# Check if OpenAI API key is available
	if not os.getenv('OPENAI_API_KEY'):
		print('❌ Error: OPENAI_API_KEY environment variable not set')
		print('Please set your OpenAI API key to use CUA integration')
		sys.exit(1)

	# Run the example
	asyncio.run(main())
