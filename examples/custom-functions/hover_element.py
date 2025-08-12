"""
Example of implementing hover functionality for elements.

This shows how to hover over elements to trigger hover states and tooltips.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

from browser_use.agent.service import Agent, Controller
from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserSession
from browser_use.llm import ChatOpenAI

# Initialize controller
controller = Controller()


class HoverAction(BaseModel):
	"""Parameters for hover action"""

	index: int | None = None
	xpath: str | None = None
	selector: str | None = None


@controller.registry.action(
	'Hover over an element',
	param_model=HoverAction,  # Define this model with at least "index: int" field
)
async def hover_element(params: HoverAction, browser_session: BrowserSession):
	"""
	Hovers over the element specified by its index from the cached selector map or by XPath.
	"""
	try:
		element_node = None

		if params.xpath:
			# Find element by XPath using CDP
			cdp_session = await browser_session.get_or_create_cdp_session()
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': f"""
						(() => {{
							const element = document.evaluate('{params.xpath}', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
							if (element) {{
								const rect = element.getBoundingClientRect();
								return {{found: true, x: rect.x + rect.width/2, y: rect.y + rect.height/2}};
							}}
							return {{found: false}};
						}})()
					""",
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			element_info = result.get('result', {}).get('value', {})
			if not element_info.get('found'):
				raise Exception(f'Failed to locate element with XPath {params.xpath}')
			x, y = element_info['x'], element_info['y']

		elif params.selector:
			# Find element by CSS selector using CDP
			cdp_session = await browser_session.get_or_create_cdp_session()
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': f"""
						(() => {{
							const element = document.querySelector('{params.selector}');
							if (element) {{
								const rect = element.getBoundingClientRect();
								return {{found: true, x: rect.x + rect.width/2, y: rect.y + rect.height/2}};
							}}
							return {{found: false}};
						}})()
					""",
					'returnByValue': True,
				},
				session_id=cdp_session.session_id,
			)
			element_info = result.get('result', {}).get('value', {})
			if not element_info.get('found'):
				raise Exception(f'Failed to locate element with CSS Selector {params.selector}')
			x, y = element_info['x'], element_info['y']

		elif params.index is not None:
			# Use index to locate the element
			selector_map = await browser_session.get_selector_map()
			if params.index not in selector_map:
				raise Exception(f'Element index {params.index} does not exist - retry or use alternative actions')
			element_node = selector_map[params.index]

			# Get element position
			if not element_node.absolute_position:
				raise Exception(f'Element at index {params.index} has no position information')

			x = element_node.absolute_position.x + element_node.absolute_position.width / 2
			y = element_node.absolute_position.y + element_node.absolute_position.height / 2

		else:
			raise Exception('Either index, xpath, or selector must be provided')

		# Perform hover using CDP mouse events
		cdp_session = await browser_session.get_or_create_cdp_session()

		# Move mouse to the element position
		await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
			params={
				'type': 'mouseMoved',
				'x': x,
				'y': y,
			},
			session_id=cdp_session.session_id,
		)

		# Wait a bit for hover state to trigger
		await asyncio.sleep(0.1)

		msg = (
			f'🖱️ Hovered over element at index {params.index}'
			if params.index is not None
			else f'🖱️ Hovered over element with XPath {params.xpath}'
			if params.xpath
			else f'🖱️ Hovered over element with selector {params.selector}'
		)
		return ActionResult(extracted_content=msg, include_in_memory=True)

	except Exception as e:
		error_msg = f'❌ Failed to hover over element: {str(e)}'
		return ActionResult(error=error_msg)


async def main():
	"""Main function to run the example"""
	browser_session = BrowserSession()
	await browser_session.start()
	llm = ChatOpenAI(model='gpt-4.1')

	# Create the agent with hover capability
	agent = Agent(
		task="""
            Go to a website with hover interactions, like https://www.w3schools.com/howto/howto_css_dropdown.asp
            Try hovering over the dropdown menu to see the dropdown items appear.
            Then describe what happens when you hover.
        """,
		llm=llm,
		browser_session=browser_session,
		controller=controller,
	)

	# Run the agent
	await agent.run(max_steps=10)

	# Cleanup
	await browser_session.kill()


if __name__ == '__main__':
	asyncio.run(main())
