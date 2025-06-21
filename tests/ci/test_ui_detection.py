import pytest
from playwright.async_api import async_playwright

from browser_use.dom.service import DomService
from browser_use.dom.views import DOMElementNode

# Define the test cases
test_cases = [
	{
		'name': 'Simple login form',
		'html': """
            <html><body>
                <form>
                    <input type='text' id='username' placeholder='Username'>
                    <input type='password' id='password'>
                    <button type='submit'>Login</button>
                </form>
            </body></html>
        """,
		'expected': [
			{'tag_name': 'input', 'attributes': {'type': 'text', 'id': 'username'}},
			{'tag_name': 'input', 'attributes': {'type': 'password', 'id': 'password'}},
			{'tag_name': 'button', 'attributes': {'type': 'submit'}},
		],
	},
	{
		'name': 'Hidden input should not be visible',
		'html': """
            <html><body>
                <input type='hidden' id='secret'>
                <input type='checkbox' id='agree'>
            </body></html>
        """,
		'expected': [
			{'tag_name': 'input', 'attributes': {'type': 'checkbox', 'id': 'agree'}},
		],
	},
	{
		'name': 'Disabled elements',
		'html': """
            <html><body>
                <button disabled>Can't click</button>
                <a href='https://example.com'>Link</a>
            </body></html>
        """,
		'expected': [
			{'tag_name': 'a', 'attributes': {'href': 'https://example.com'}},
		],
	},
	{
		'name': 'Nested interactive elements',
		'html': """
            <html><body>
                <div id="outer">
                    <button id="inner">Click</button>
                </div>
            </body></html>
        """,
		'expected': [
			{'tag_name': 'button', 'attributes': {'id': 'inner'}},
		],
	},
	{
		'name': 'Overlapping elements',
		'html': """
            <html><body>
                <style>
                    .overlap {
                        position: absolute;
                        top: 0;
                        left: 0;
                        width: 100px;
                        height: 100px;
                    }
                </style>
                <button class="overlap" id="top">Top</button>
                <button class="overlap" id="bottom">Bottom</button>
            </body></html>
        """,
		'expected': [
			{'tag_name': 'button', 'attributes': {'id': 'bottom'}},
		],
	},
	{
		'name': 'SVG interactive elements',
		'html': """
            <html><body>
                <svg width="100" height="100">
                    <circle cx="50" cy="50" r="40" fill="red" onclick="alert('clicked')"/>
                </svg>
            </body></html>
        """,
		'expected': [],
	},
	{
		'name': 'Iframe elements',
		'html': """
            <html><body>
                <iframe src="about:blank" id="frame"></iframe>
                <button id="main">Main Button</button>
            </body></html>
        """,
		'expected': [
			{'tag_name': 'button', 'attributes': {'id': 'main'}},
		],
	},
	{
		'name': 'Elements with display: none',
		'html': """
            <html><body>
                <style>
                    .hidden {
                        display: none;
                    }
                </style>
                <button class="hidden" id="hidden">Hidden</button>
                <button id="visible">Visible</button>
            </body></html>
        """,
		'expected': [
			{'tag_name': 'button', 'attributes': {'id': 'visible'}},
		],
	},
	{
		'name': 'Elements with opacity: 0',
		'html': """
            <html><body>
                <style>
                    .invisible {
                        opacity: 0;
                    }
                </style>
                <button class="invisible" id="invisible">Invisible</button>
                <button id="visible">Visible</button>
            </body></html>
        """,
		'expected': [
			{'tag_name': 'button', 'attributes': {'id': 'visible'}},
		],
	},
	{
		'name': 'Custom cursor elements',
		'html': """
            <html><body>
                <style>
                    .custom-cursor {
                        cursor: pointer;
                    }
                </style>
                <div class="custom-cursor" id="custom">Custom Cursor</div>
                <button id="regular">Regular Button</button>
            </body></html>
        """,
		'expected': [
			{'tag_name': 'div', 'attributes': {'id': 'custom'}},
			{'tag_name': 'button', 'attributes': {'id': 'regular'}},
		],
	},
	{
		'name': 'Elements with pointer-events: none',
		'html': """
            <html><body>
                <style>
                    .no-pointer {
                        pointer-events: none;
                    }
                </style>
                <button class="no-pointer" id="blocked">Blocked</button>
                <button id="normal">Normal</button>
            </body></html>
        """,
		'expected': [
			{'tag_name': 'button', 'attributes': {'id': 'normal'}},
		],
	},
]


@pytest.mark.asyncio
@pytest.mark.parametrize('case', test_cases, ids=[c['name'] for c in test_cases])
async def test_ui_detection(case):
	async with async_playwright() as p:
		browser = await p.chromium.launch()
		page = await browser.new_page()
		try:
			await page.goto(f'data:text/html,{case["html"]}')
			dom_service = DomService(page)
			state = await dom_service.get_clickable_elements()

			def walk_tree(node):
				yield node
				for child in node.children:
					if isinstance(child, DOMElementNode):
						yield from walk_tree(child)

			# Collect actual elements (filtered by interactivity and visibility)
			actual_elements = []
			for node in walk_tree(state.element_tree):
				if node.is_interactive and node.is_visible:
					actual_elements.append(
						{
							'tag_name': node.tag_name,
							'attributes': node.attributes,
						}
					)

			# Normalize: Only include expected keys in attributes
			normalized_actual = []
			for actual in actual_elements:
				for expected in case['expected']:
					if actual['tag_name'] == expected['tag_name']:
						filtered_attrs = {k: v for k, v in actual['attributes'].items() if k in expected['attributes']}
						normalized_actual.append({'tag_name': actual['tag_name'], 'attributes': filtered_attrs})
						break

			# assert actual detection with excepted
			assert normalized_actual == case['expected']

		finally:
			await page.close()
			await browser.close()
