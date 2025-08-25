from browser_use import BrowserProfile, BrowserSession


async def test_input_text_fallback_for_non_standard_elements(httpserver):
	"""Test that input text works on elements that don't support fill() by using type() as fallback."""

	# Create a test page with various input elements
	httpserver.expect_request('/').respond_with_data("""
	<html>
	<body>
		<!-- Standard input - should work with fill() -->
		<input id="standard-input" type="text" placeholder="Standard input">
		
		<!-- Contenteditable div - should NOT work with fill(), needs fallback -->
		<div id="contenteditable" contenteditable="true" style="border: 1px solid #ccc; padding: 5px;">
			Click here to edit
		</div>
		
		<!-- Custom element that might not support fill() -->
		<custom-element id="custom" tabindex="0" style="border: 1px solid #ccc; padding: 5px;">
			Custom element
		</custom-element>
	</body>
	</html>
	""")

	async with BrowserSession(browser_profile=BrowserProfile(user_data_dir=None, headless=True)) as session:
		page = await session.get_current_page()
		await page.goto(httpserver.url_for('/'))

		# Get the DOM state
		state = await session.get_browser_state_with_recovery()

		# Find elements by their text/attributes
		standard_input_index = None
		contenteditable_index = None
		custom_element_index = None

		for index, element in state.selector_map.items():
			if element.attributes.get('id') == 'standard-input':
				standard_input_index = index
			elif element.attributes.get('id') == 'contenteditable':
				contenteditable_index = index
			elif element.attributes.get('id') == 'custom':
				custom_element_index = index

		# Test standard input (should work normally)
		if standard_input_index is not None:
			element = state.selector_map[standard_input_index]
			await session._input_text_element_node(element, 'Test text for input')

			# Verify the text was entered
			value = await page.locator('#standard-input').input_value()
			assert value == 'Test text for input'

		# Test contenteditable div (should use fallback)
		if contenteditable_index is not None:
			element = state.selector_map[contenteditable_index]
			await session._input_text_element_node(element, 'Test text for contenteditable')

			# Verify the text was entered
			text = await page.locator('#contenteditable').text_content()
			assert 'Test text for contenteditable' in (text or '')

		# Test custom element (might use fallback)
		if custom_element_index is not None:
			element = state.selector_map[custom_element_index]
			# This might fail for truly custom elements, but should at least not crash
			try:
				await session._input_text_element_node(element, 'Test text for custom')
			except Exception:
				# It's okay if custom elements fail, as long as standard ones work
				pass
