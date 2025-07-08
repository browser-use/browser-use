import asyncio

import pytest
from pytest_httpserver import HTTPServer

from browser_use import BrowserSession
from browser_use.browser import BrowserProfile


@pytest.fixture
def cross_origin_iframe_html():
	"""HTML pages for testing cross-origin iframe handling."""

	# Main page (served on one port)
	main_page = """
	<!DOCTYPE html>
	<html>
	<head><title>Main Page</title></head>
	<body>
		<h1>Main Page Content</h1>
		<button id="main-button">Main Button</button>
		<input type="text" id="main-input" placeholder="Main input">
		
		<!-- Cross-origin iframe -->
		<iframe 
			id="frame1" 
			src="{frame1_url}" 
			width="600" 
			height="400"
			style="border: 2px solid blue;">
		</iframe>
		
		<p>Some text after iframe</p>
		<a href="#" id="main-link">Main Link</a>
	</body>
	</html>
	"""

	# First iframe content (served on different port)
	frame1_content = """
	<!DOCTYPE html>
	<html>
	<head><title>Frame 1</title></head>
	<body style="background: #f0f0f0;">
		<h2>Frame 1 Content</h2>
		<form id="frame1-form">
			<input type="text" id="frame1-input" placeholder="Frame 1 input">
			<select id="frame1-select">
				<option value="opt1">Option 1</option>
				<option value="opt2">Option 2</option>
			</select>
			<button type="submit" id="frame1-submit">Submit Frame 1</button>
		</form>
		
		<!-- Nested cross-origin iframe -->
		<iframe 
			id="frame2" 
			src="{frame2_url}" 
			width="500" 
			height="300"
			style="border: 2px solid green;">
		</iframe>
	</body>
	</html>
	"""

	# Second nested iframe content (served on yet another port/path)
	frame2_content = """
	<!DOCTYPE html>
	<html>
	<head><title>Frame 2</title></head>
	<body style="background: #e0e0e0;">
		<h3>Frame 2 Content (Nested)</h3>
		<div id="frame2-container">
			<input type="email" id="frame2-email" placeholder="Email in Frame 2">
			<textarea id="frame2-textarea" placeholder="Text area in Frame 2"></textarea>
			<button id="frame2-button">Click Me in Frame 2</button>
			
			<!-- Even deeper nesting -->
			<iframe 
				id="frame3" 
				src="{frame3_url}" 
				width="400" 
				height="200"
				style="border: 2px solid red;">
			</iframe>
		</div>
	</body>
	</html>
	"""

	# Third level nested iframe
	frame3_content = """
	<!DOCTYPE html>
	<html>
	<head><title>Frame 3</title></head>
	<body style="background: #d0d0d0;">
		<h4>Frame 3 Content (Deeply Nested)</h4>
		<form id="frame3-form">
			<input type="password" id="frame3-password" placeholder="Password">
			<input type="checkbox" id="frame3-checkbox"> Remember me
			<button type="button" id="frame3-button">Deep Button</button>
		</form>
	</body>
	</html>
	"""

	return {'main': main_page, 'frame1': frame1_content, 'frame2': frame2_content, 'frame3': frame3_content}


@pytest.fixture
def setup_cross_origin_servers(httpserver: HTTPServer, cross_origin_iframe_html):
	"""Set up multiple HTTP servers to simulate cross-origin iframes."""
	import socket

	from pytest_httpserver import HTTPServer as HTTPServerClass

	# Main server (already provided by httpserver fixture)
	main_port = httpserver.port

	# Create additional servers for cross-origin simulation
	# Find available ports
	def get_free_port():
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
			s.bind(('', 0))
			s.listen(1)
			port = s.getsockname()[1]
		return port

	frame1_port = get_free_port()
	frame2_port = get_free_port()
	frame3_port = get_free_port()

	# Create additional HTTP servers
	frame1_server = HTTPServerClass(host='127.0.0.1', port=frame1_port)
	frame2_server = HTTPServerClass(host='127.0.0.1', port=frame2_port)
	frame3_server = HTTPServerClass(host='127.0.0.1', port=frame3_port)

	frame1_server.start()
	frame2_server.start()
	frame3_server.start()

	# URLs for each frame
	main_url = f'http://127.0.0.1:{main_port}'
	frame1_url = f'http://127.0.0.1:{frame1_port}/frame1'
	frame2_url = f'http://127.0.0.1:{frame2_port}/frame2'
	frame3_url = f'http://127.0.0.1:{frame3_port}/frame3'

	# Set up routes with proper iframe URLs injected
	httpserver.expect_request('/').respond_with_data(
		cross_origin_iframe_html['main'].format(frame1_url=frame1_url), content_type='text/html'
	)

	frame1_server.expect_request('/frame1').respond_with_data(
		cross_origin_iframe_html['frame1'].format(frame2_url=frame2_url), content_type='text/html'
	)

	frame2_server.expect_request('/frame2').respond_with_data(
		cross_origin_iframe_html['frame2'].format(frame3_url=frame3_url), content_type='text/html'
	)

	frame3_server.expect_request('/frame3').respond_with_data(cross_origin_iframe_html['frame3'], content_type='text/html')

	yield {
		'main_url': main_url,
		'servers': {'main': httpserver, 'frame1': frame1_server, 'frame2': frame2_server, 'frame3': frame3_server},
	}

	# Cleanup
	frame1_server.stop()
	frame2_server.stop()
	frame3_server.stop()


@pytest.mark.asyncio
async def test_cross_origin_iframe_detection_current_behavior(setup_cross_origin_servers):
	"""Test current behavior with cross-origin iframes - demonstrates the problem."""
	servers_info = setup_cross_origin_servers
	main_url = servers_info['main_url']

	profile = BrowserProfile(headless=True)
	session = BrowserSession(browser_profile=profile)
	try:
		await session.start()
		page = await session.get_current_page()
		await page.goto(main_url)

		# Wait for all iframes to load
		await page.wait_for_load_state('networkidle')
		await asyncio.sleep(1)  # Extra wait for nested iframes

		# Get the current DOM tree (without CDP)
		from browser_use.dom.service import DomService

		dom_service = DomService(page, logger=session.logger)
		dom_state = await dom_service.get_clickable_elements(highlight_elements=True)

		# Extract all interactive elements
		interactive_elements = []

		def collect_interactive_elements(node, elements_list):
			"""Recursively collect all interactive elements."""
			if hasattr(node, 'is_interactive') and node.is_interactive:
				elements_list.append(
					{
						'tag': node.tag_name,
						'xpath': node.xpath,
						'highlight_index': node.highlight_index,
						'attributes': node.attributes,
					}
				)

			if hasattr(node, 'children'):
				for child in node.children:
					collect_interactive_elements(child, elements_list)

		collect_interactive_elements(dom_state.element_tree, interactive_elements)

		# Check what elements were found
		found_ids = {elem['attributes'].get('id') for elem in interactive_elements if 'id' in elem['attributes']}
		print(f'\nFound elements: {found_ids}')

		# Expected elements in main frame only (current behavior)
		main_frame_ids = {'main-button', 'main-input', 'main-link'}

		# Elements that SHOULD be found but won't be due to cross-origin
		cross_origin_ids = {
			'frame1-input',
			'frame1-select',
			'frame1-submit',
			'frame2-email',
			'frame2-textarea',
			'frame2-button',
			'frame3-password',
			'frame3-checkbox',
			'frame3-button',
		}

		# Current behavior: only main frame elements are found
		assert main_frame_ids.issubset(found_ids), f'Main frame elements missing: {main_frame_ids - found_ids}'

		# This assertion will fail - demonstrating the problem
		missing_cross_origin = cross_origin_ids - found_ids
		print(f'\nMissing cross-origin elements: {missing_cross_origin}')
		assert not missing_cross_origin, f'Cross-origin elements not detected: {missing_cross_origin}'
	finally:
		await session.close()


@pytest.mark.asyncio
async def test_cross_origin_iframe_unified_tree_with_cdp(setup_cross_origin_servers):
	"""Test that unified tree can detect all elements across cross-origin iframes using CDP."""
	servers_info = setup_cross_origin_servers
	main_url = servers_info['main_url']

	profile = BrowserProfile(headless=True)
	session = BrowserSession(browser_profile=profile)
	try:
		await session.start()
		page = await session.get_current_page()
		await page.goto(main_url)

		# Wait for all iframes to load
		await page.wait_for_load_state('networkidle')
		await asyncio.sleep(1)

		# This is what we want to implement - get unified tree with CDP
		# For now, let's test what CDP can access

		# Create CDP session for main frame
		cdp_session = await page.context.new_cdp_session(page)

		# Enable required domains
		await cdp_session.send('Accessibility.enable')
		await cdp_session.send('DOM.enable')

		# Get accessibility tree
		ax_tree = await cdp_session.send('Accessibility.getFullAXTree')

		# Check if we can see iframe content
		def count_nodes(node, depth=0):
			"""Count nodes in accessibility tree."""
			count = 1
			indent = '  ' * depth
			role = node.get('role', {}).get('value', 'unknown')
			name = node.get('name', {}).get('value', '')
			print(f'{indent}{role}: {name}')

			for child_id in node.get('childIds', []):
				# In a real implementation, we'd need to look up the child node
				count += 1

			return count

		if 'root' in ax_tree:
			print('\nAccessibility tree from main frame:')
			node_count = count_nodes(ax_tree['root'])
			print(f'\nTotal nodes in main frame: {node_count}')

		# Try to access other frames
		print(f'\nTotal frames found: {len(page.frames)}')
		for i, frame in enumerate(page.frames):
			print(f'Frame {i}: {frame.url}')

			# For cross-origin frames, we need separate CDP sessions
			if frame != page.main_frame:
				try:
					frame_cdp = await page.context.new_cdp_session(frame)
					await frame_cdp.send('Accessibility.enable')
					frame_ax_tree = await frame_cdp.send('Accessibility.getFullAXTree')
					print(f'  - Successfully got accessibility tree for frame {i}')
					await frame_cdp.detach()
				except Exception as e:
					print(f'  - Failed to access frame {i}: {e}')

		# This test demonstrates what we need to implement:
		# 1. Create CDP sessions for each frame
		# 2. Get accessibility trees from all frames
		# 3. Merge them with unique IDs
		# 4. Build unified XPaths that cross frame boundaries
	finally:
		await session.close()


@pytest.mark.asyncio
async def test_desired_unified_tree_behavior(setup_cross_origin_servers):
	"""Test demonstrating the desired behavior with unified tree."""
	servers_info = setup_cross_origin_servers
	main_url = servers_info['main_url']

	profile = BrowserProfile(headless=True)
	session = BrowserSession(browser_profile=profile)
	try:
		await session.start()
		page = await session.get_current_page()
		await page.goto(main_url)

		# Wait for all iframes to load
		await page.wait_for_load_state('networkidle')
		await asyncio.sleep(1)

		# What we want to achieve:
		# 1. Get unified tree that includes all frames
		unified_tree = {
			'tag': 'body',
			'encoded_id': 'f0:n1',
			'children': [
				{'tag': 'h1', 'encoded_id': 'f0:n2'},
				{'tag': 'button', 'id': 'main-button', 'encoded_id': 'f0:n3'},
				{'tag': 'input', 'id': 'main-input', 'encoded_id': 'f0:n4'},
				{
					'tag': 'iframe',
					'id': 'frame1',
					'encoded_id': 'f0:n5',
					'frame_ordinal': 1,
					'children': [
						# Frame 1 content with f1: prefix
						{'tag': 'h2', 'encoded_id': 'f1:n1'},
						{'tag': 'input', 'id': 'frame1-input', 'encoded_id': 'f1:n2'},
						{'tag': 'select', 'id': 'frame1-select', 'encoded_id': 'f1:n3'},
						{'tag': 'button', 'id': 'frame1-submit', 'encoded_id': 'f1:n4'},
						{
							'tag': 'iframe',
							'id': 'frame2',
							'encoded_id': 'f1:n5',
							'frame_ordinal': 2,
							'children': [
								# Frame 2 content with f2: prefix
								{'tag': 'input', 'id': 'frame2-email', 'encoded_id': 'f2:n1'},
								{'tag': 'textarea', 'id': 'frame2-textarea', 'encoded_id': 'f2:n2'},
								{'tag': 'button', 'id': 'frame2-button', 'encoded_id': 'f2:n3'},
								{
									'tag': 'iframe',
									'id': 'frame3',
									'encoded_id': 'f2:n4',
									'frame_ordinal': 3,
									'children': [
										# Frame 3 content with f3: prefix
										{'tag': 'input', 'id': 'frame3-password', 'encoded_id': 'f3:n1'},
										{'tag': 'input', 'id': 'frame3-checkbox', 'encoded_id': 'f3:n2'},
										{'tag': 'button', 'id': 'frame3-button', 'encoded_id': 'f3:n3'},
									],
								},
							],
						},
					],
				},
				{'tag': 'p', 'encoded_id': 'f0:n6'},
				{'tag': 'a', 'id': 'main-link', 'encoded_id': 'f0:n7'},
			],
		}

		# 2. Deep XPaths that include frame traversal
		expected_xpaths = {
			'main-button': '//button[@id="main-button"]',
			'frame1-input': '//iframe[@id="frame1"]//input[@id="frame1-input"]',
			'frame2-email': '//iframe[@id="frame1"]//iframe[@id="frame2"]//input[@id="frame2-email"]',
			'frame3-button': '//iframe[@id="frame1"]//iframe[@id="frame2"]//iframe[@id="frame3"]//button[@id="frame3-button"]',
		}

		# 3. Ability to click elements in any frame
		# await session.click_element_by_encoded_id('f3:n3')  # Click button in deepest frame

		print('\nThis test demonstrates the desired unified tree structure')
		print('with encoded IDs and deep XPaths for cross-frame navigation')
	finally:
		await session.close()
