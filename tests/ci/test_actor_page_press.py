"""Test for Page.press() keyboard input functionality."""

from pytest_httpserver import HTTPServer


async def test_press_arrow_keys(browser_session, httpserver: HTTPServer):
	"""Test that arrow keys are properly sent with correct key codes."""
	# HTML page that captures keyboard events and displays them
	html_content = """
	<!DOCTYPE html>
	<html>
	<head>
		<title>Key Press Test</title>
	</head>
	<body>
		<div id="output">Ready</div>
		<script>
			const output = document.getElementById('output');
			const pressedKeys = [];

			document.addEventListener('keydown', (e) => {
				pressedKeys.push({
					key: e.key,
					code: e.code,
					keyCode: e.keyCode
				});
				output.textContent = JSON.stringify(pressedKeys);
			});
		</script>
	</body>
	</html>
	"""

	# Serve the test HTML
	httpserver.expect_request('/').respond_with_data(html_content, content_type='text/html')
	test_url = httpserver.url_for('/')

	# Navigate to test page
	page = await browser_session.new_page(test_url)

	# Wait for page to load
	import asyncio

	await asyncio.sleep(0.5)

	# Press arrow keys
	await page.press('ArrowUp')
	await asyncio.sleep(0.1)
	await page.press('ArrowDown')
	await asyncio.sleep(0.1)
	await page.press('ArrowLeft')
	await asyncio.sleep(0.1)
	await page.press('ArrowRight')
	await asyncio.sleep(0.1)

	# Get the output text that contains captured key events
	output_text = await page.evaluate('() => document.getElementById("output").textContent')

	# Parse the JSON
	import json

	pressed_keys = json.loads(output_text)

	# Verify we captured 4 key presses
	assert len(pressed_keys) == 4, f'Expected 4 key presses, got {len(pressed_keys)}'

	# Verify arrow keys were captured with correct properties
	assert pressed_keys[0]['key'] == 'ArrowUp'
	assert pressed_keys[0]['code'] == 'ArrowUp'
	assert pressed_keys[0]['keyCode'] == 38

	assert pressed_keys[1]['key'] == 'ArrowDown'
	assert pressed_keys[1]['code'] == 'ArrowDown'
	assert pressed_keys[1]['keyCode'] == 40

	assert pressed_keys[2]['key'] == 'ArrowLeft'
	assert pressed_keys[2]['code'] == 'ArrowLeft'
	assert pressed_keys[2]['keyCode'] == 37

	assert pressed_keys[3]['key'] == 'ArrowRight'
	assert pressed_keys[3]['code'] == 'ArrowRight'
	assert pressed_keys[3]['keyCode'] == 39


async def test_press_special_keys(browser_session, httpserver: HTTPServer):
	"""Test that special keys (Enter, Escape, etc.) work correctly."""
	html_content = """
	<!DOCTYPE html>
	<html>
	<head>
		<title>Special Key Test</title>
	</head>
	<body>
		<div id="output">Ready</div>
		<script>
			const output = document.getElementById('output');
			const pressedKeys = [];

			document.addEventListener('keydown', (e) => {
				pressedKeys.push({
					key: e.key,
					code: e.code,
					keyCode: e.keyCode
				});
				output.textContent = JSON.stringify(pressedKeys);
			});
		</script>
	</body>
	</html>
	"""

	httpserver.expect_request('/').respond_with_data(html_content, content_type='text/html')
	test_url = httpserver.url_for('/')

	page = await browser_session.new_page(test_url)

	import asyncio

	await asyncio.sleep(0.5)

	# Press special keys
	await page.press('Enter')
	await asyncio.sleep(0.1)
	await page.press('Escape')
	await asyncio.sleep(0.1)
	await page.press('Tab')
	await asyncio.sleep(0.1)

	# Get the output
	output_text = await page.evaluate('() => document.getElementById("output").textContent')

	import json

	pressed_keys = json.loads(output_text)

	# Verify special keys
	assert len(pressed_keys) == 3

	assert pressed_keys[0]['key'] == 'Enter'
	assert pressed_keys[0]['code'] == 'Enter'
	assert pressed_keys[0]['keyCode'] == 13

	assert pressed_keys[1]['key'] == 'Escape'
	assert pressed_keys[1]['code'] == 'Escape'
	assert pressed_keys[1]['keyCode'] == 27

	assert pressed_keys[2]['key'] == 'Tab'
	assert pressed_keys[2]['code'] == 'Tab'
	assert pressed_keys[2]['keyCode'] == 9


async def test_press_key_combinations(browser_session, httpserver: HTTPServer):
	"""Test that key combinations like Control+A work correctly."""
	html_content = """
	<!DOCTYPE html>
	<html>
	<head>
		<title>Key Combination Test</title>
	</head>
	<body>
		<div id="output">Ready</div>
		<script>
			const output = document.getElementById('output');
			const events = [];

			document.addEventListener('keydown', (e) => {
				events.push({
					type: 'down',
					key: e.key,
					code: e.code,
					ctrlKey: e.ctrlKey,
					shiftKey: e.shiftKey
				});
				output.textContent = JSON.stringify(events);
			});

			document.addEventListener('keyup', (e) => {
				events.push({
					type: 'up',
					key: e.key,
					code: e.code
				});
				output.textContent = JSON.stringify(events);
			});
		</script>
	</body>
	</html>
	"""

	httpserver.expect_request('/').respond_with_data(html_content, content_type='text/html')
	test_url = httpserver.url_for('/')

	page = await browser_session.new_page(test_url)

	import asyncio

	await asyncio.sleep(0.5)

	# Press Control+A
	await page.press('Control+a')
	await asyncio.sleep(0.2)

	# Get the output
	output_text = await page.evaluate('() => document.getElementById("output").textContent')

	import json

	events = json.loads(output_text)

	# Should have: Control down, 'a' down, 'a' up, Control up
	assert len(events) >= 4

	# Find the 'a' keydown event - should have ctrlKey=true
	a_down_events = [e for e in events if e['type'] == 'down' and e['key'] == 'a']
	assert len(a_down_events) > 0
	assert a_down_events[0]['ctrlKey'] is True, 'Control modifier should be active when pressing "a"'


async def test_press_letter_keys(browser_session, httpserver: HTTPServer):
	"""Test that letter keys work correctly."""
	html_content = """
	<!DOCTYPE html>
	<html>
	<head>
		<title>Letter Key Test</title>
	</head>
	<body>
		<div id="output">Ready</div>
		<script>
			const output = document.getElementById('output');
			const pressedKeys = [];

			document.addEventListener('keydown', (e) => {
				pressedKeys.push({
					key: e.key,
					code: e.code
				});
				output.textContent = JSON.stringify(pressedKeys);
			});
		</script>
	</body>
	</html>
	"""

	httpserver.expect_request('/').respond_with_data(html_content, content_type='text/html')
	test_url = httpserver.url_for('/')

	page = await browser_session.new_page(test_url)

	import asyncio

	await asyncio.sleep(0.5)

	# Press letter keys
	await page.press('a')
	await asyncio.sleep(0.1)
	await page.press('B')
	await asyncio.sleep(0.1)

	# Get the output
	output_text = await page.evaluate('() => document.getElementById("output").textContent')

	import json

	pressed_keys = json.loads(output_text)

	# Verify letter keys
	assert len(pressed_keys) == 2

	assert pressed_keys[0]['key'] == 'a'
	assert pressed_keys[0]['code'] == 'KeyA'

	assert pressed_keys[1]['key'] == 'B'
	assert pressed_keys[1]['code'] == 'KeyB'


async def test_press_arrow_keys_game_simulation(browser_session, httpserver: HTTPServer):
	"""Test arrow keys in a 2048-like game scenario."""
	# Simulate a simple game that responds to arrow keys
	html_content = """
	<!DOCTYPE html>
	<html>
	<head>
		<title>2048-like Game Test</title>
		<style>
			#game-container {
				width: 400px;
				height: 400px;
				background: #bbada0;
				position: relative;
			}
			#score {
				font-size: 24px;
				margin-bottom: 10px;
			}
			#moves-log {
				margin-top: 10px;
				font-family: monospace;
			}
		</style>
	</head>
	<body>
		<div id="score">Score: <span id="score-value">0</span></div>
		<div id="game-container"></div>
		<div id="moves-log"></div>
		<script>
			let score = 0;
			const moves = [];
			const scoreElement = document.getElementById('score-value');
			const movesLog = document.getElementById('moves-log');

			// Listen for arrow key presses
			document.addEventListener('keydown', (e) => {
				let direction = null;

				if (e.key === 'ArrowUp' || e.code === 'ArrowUp') {
					direction = 'up';
					e.preventDefault();
				} else if (e.key === 'ArrowDown' || e.code === 'ArrowDown') {
					direction = 'down';
					e.preventDefault();
				} else if (e.key === 'ArrowLeft' || e.code === 'ArrowLeft') {
					direction = 'left';
					e.preventDefault();
				} else if (e.key === 'ArrowRight' || e.code === 'ArrowRight') {
					direction = 'right';
					e.preventDefault();
				}

				if (direction) {
					// Simulate game move
					score += 10;
					moves.push(direction);
					scoreElement.textContent = score;
					movesLog.textContent = moves.join(', ');
				}
			});
		</script>
	</body>
	</html>
	"""

	# Serve the test HTML
	httpserver.expect_request('/').respond_with_data(html_content, content_type='text/html')
	test_url = httpserver.url_for('/')

	# Navigate to test page
	page = await browser_session.new_page(test_url)

	import asyncio

	await asyncio.sleep(0.5)

	# Play the game with arrow keys (like 2048)
	await page.press('ArrowLeft')
	await asyncio.sleep(0.2)
	await page.press('ArrowUp')
	await asyncio.sleep(0.2)
	await page.press('ArrowDown')
	await asyncio.sleep(0.2)
	await page.press('ArrowRight')
	await asyncio.sleep(0.2)

	# Get the score and moves
	score_text = await page.evaluate('() => document.getElementById("score-value").textContent')
	moves_text = await page.evaluate('() => document.getElementById("moves-log").textContent')

	# Verify the game registered all moves
	assert score_text == '40', f'Expected score of 40, got {score_text}'
	assert moves_text == 'left, up, down, right', f'Expected "left, up, down, right", got {moves_text}'
