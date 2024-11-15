import time

from browser_use.browser.service import Browser
from browser_use.dom.service import DomService
from browser_use.utils import time_execution_sync


def test_highlight_elements():
	browser = Browser(headless=False)

	driver = browser.init()

	dom_service = DomService(driver)

	browser.go_to_url('https://www.kayak.ch')
	# browser.go_to_url('https://google.com/flights')
	# browser.go_to_url('https://immobilienscout24.de')

	time.sleep(1)
	# browser._click_element_by_xpath(
	# 	'/html/body/div[5]/div/div[2]/div/div/div[3]/div/div[1]/button[1]'
	# )
	# browser._click_element_by_xpath("//button[div/div[text()='Alle akzeptieren']]")

	elements = time_execution_sync('get_clickable_elements')(dom_service.get_clickable_elements)()

	time_execution_sync('highlight_selector_map_elements')(browser.highlight_selector_map_elements)(
		elements.selector_map
	)

	print(elements.dom_items_to_string(use_tabs=False))

	# Find and print duplicate XPaths
	xpath_counts = {}
	for selector in elements.selector_map.values():
		if selector in xpath_counts:
			xpath_counts[selector] += 1
		else:
			xpath_counts[selector] = 1

	print('\nDuplicate XPaths found:')
	for xpath, count in xpath_counts.items():
		if count > 1:
			print(f'XPath: {xpath}')
			print(f'Count: {count}\n')

	input('Press Enter to continue...')


def main():
	test_highlight_elements()


if __name__ == '__main__':
	main()
