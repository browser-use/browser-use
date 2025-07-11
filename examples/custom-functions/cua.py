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

from browser_use import Agent, Controller
from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.llm import ChatOpenAI

try:
	from lmnr import Laminar

	Laminar.initialize(project_api_key=os.getenv('LMNR_PROJECT_API_KEY'))
except ImportError:
	pass


class OpenAICUAAction(BaseModel):
	"""Parameters for OpenAI Computer Use Assistant action."""

	description: str = Field(..., description='Description of your next goal')


async def handle_model_action(page, action) -> ActionResult:
	"""
	Given a computer action (e.g., click, double_click, scroll, etc.),
	execute the corresponding operation on the Playwright page.
	"""
	action_type = action.type
	ERROR_MSG: str = 'Could not execute the CUA action.'

	try:
		match action_type:
			case 'click':
				x, y = action.x, action.y
				button = action.button
				print(f"Action: click at ({x}, {y}) with button '{button}'")
				# Not handling things like middle click, etc.
				if button != 'left' and button != 'right':
					button = 'left'
				await page.mouse.click(x, y, button=button)
				msg = f'Clicked at ({x}, {y}) with button {button}'
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'scroll':
				x, y = action.x, action.y
				scroll_x, scroll_y = action.scroll_x, action.scroll_y
				print(f'Action: scroll at ({x}, {y}) with offsets (scroll_x={scroll_x}, scroll_y={scroll_y})')
				await page.mouse.move(x, y)
				await page.evaluate(f'window.scrollBy({scroll_x}, {scroll_y})')
				msg = f'Scrolled at ({x}, {y}) with offsets (scroll_x={scroll_x}, scroll_y={scroll_y})'
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'keypress':
				keys = action.keys
				for k in keys:
					print(f"Action: keypress '{k}'")
					# A simple mapping for common keys; expand as needed.
					if k.lower() == 'enter':
						await page.keyboard.press('Enter')
					elif k.lower() == 'space':
						await page.keyboard.press(' ')
					else:
						await page.keyboard.press(k)
				msg = f'Pressed keys: {keys}'
				return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

			case 'type':
				text = action.text
				print(f'Action: type text: {text}')
				await page.keyboard.type(text)
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
		page = await browser_session.get_current_page()
		page_info = browser_session.browser_state_summary.page_info
		if not page_info:
			raise Exception('Page info not found - cannot execute CUA action')

		print(f'📐 Viewport size: {page_info.viewport_width}x{page_info.viewport_height}')

		screenshot_b64 = browser_session.browser_state_summary.screenshot
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

		action_result = await handle_model_action(page, action)
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
		await browser_session.close()
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
