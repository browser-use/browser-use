import time

from tokencost import count_string_tokens

from browser_use.browser.browser import Browser, BrowserConfig

# from browser_use.browser.service import Browser
from browser_use.dom.service import DomService
from browser_use.utils import time_execution_sync


# @pytest.mark.skip("slow af")
async def test_process_html_file():
	browser = Browser(config=BrowserConfig(headless=False))

	async with await browser.new_context() as context:
		page = await context.get_current_page()

		dom_service = DomService(page)

		# await page.goto('https://kayak.com/flights')
		# browser.go_to_url('https://google.com/flights')
		await page.goto('https://immobilienscout24.de')

		time.sleep(3)
		# browser._click_element_by_xpath(
		# 	'/html/body/div[5]/div/div[2]/div/div/div[3]/div/div[1]/button[1]'
		# )
		# browser._click_element_by_xpath("//button[div/div[text()='Alle akzeptieren']]")

		dom_state = await time_execution_sync('get_clickable_elements')(
			dom_service.get_clickable_elements
		)()
		elements = dom_state.element_tree
		selector_map = dom_state.selector_map

		print(elements.clickable_elements_to_string())
		print(
			'Tokens:', count_string_tokens(elements.clickable_elements_to_string(), model='gpt-4o')
		)
		print(len(selector_map.keys()), 'elements highlighted')

		input('Press Enter to continue...')
