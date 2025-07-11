import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from pydantic import BaseModel

from browser_use import Agent, Controller
from browser_use.agent.views import ActionResult
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI


class HoverAction(BaseModel):
	index: int | None = None
	xpath: str | None = None
	selector: str | None = None


browser_profile = BrowserProfile(
	headless=False,
)
controller = Controller()


@controller.registry.action(
	'Hover over an element',
	param_model=HoverAction,  # Define this model with at least "index: int" field
)
async def hover_element(params: HoverAction, browser_session: BrowserSession):
	"""
	Hovers over the element specified by its index from the cached selector map or by XPath.
	"""
	if params.xpath:
		# Use XPath to locate the element
		element_handle = await browser_session.get_locate_element_by_xpath(params.xpath)
		if element_handle is None:
			raise Exception(f'Failed to locate element with XPath {params.xpath}')
	elif params.selector:
		# Use CSS selector to locate the element
		element_handle = await browser_session.get_locate_element_by_css_selector(params.selector)
		if element_handle is None:
			raise Exception(f'Failed to locate element with CSS Selector {params.selector}')
	elif params.index is not None:
		# Use index to locate the element
		selector_map = await browser_session.get_selector_map()
		if params.index not in selector_map:
			raise Exception(f'Element index {params.index} does not exist - retry or use alternative actions')
		element_node = selector_map[params.index]
		element_handle = await browser_session.get_locate_element(element_node)
		if element_handle is None:
			raise Exception(f'Failed to locate element with index {params.index}')
	else:
		raise Exception('Either index or xpath must be provided')

	try:
		await element_handle.hover()
		msg = (
			f'🖱️ Hovered over element at index {params.index}'
			if params.index is not None
			else f'🖱️ Hovered over element with XPath {params.xpath}'
		)
		return ActionResult(extracted_content=msg, include_in_memory=True)
	except Exception as e:
		err_msg = f'❌ Failed to hover over element: {str(e)}'
		raise Exception(err_msg)


async def main():
	task = 'Open https://testpages.eviltester.com/styled/csspseudo/css-hover.html and hover the element with the css selector #hoverdivpara, then click on "Can you click me?"'
	# task = 'Open https://testpages.eviltester.com/styled/csspseudo/css-hover.html and hover the element with the xpath //*[@id="hoverdivpara"], then click on "Can you click me?"'
	model = ChatOpenAI(model='gpt-4.1')
	browser_session = BrowserSession(browser_profile=browser_profile)
	await browser_session.start()
	agent = Agent(
		task=task,
		llm=model,
		controller=controller,
		browser_session=browser_session,
	)

	await agent.run()
	await browser_session.kill()

	input('Press Enter to close...')


if __name__ == '__main__':
	asyncio.run(main())
