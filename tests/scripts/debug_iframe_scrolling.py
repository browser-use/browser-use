"""
Debug test for iframe scrolling issue where DOM tree only shows top elements after scrolling.

This test verifies that after scrolling inside an iframe, the selector_map correctly
contains lower input elements like City, State, Zip Code, etc.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import browser_use modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from browser_use.agent.service import Agent
from browser_use.agent.views import ActionModel
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import BrowserStateRequestEvent

# Import the mock LLM helper from conftest
from tests.ci.conftest import create_mock_llm


async def debug_iframe_scrolling():
	"""Debug iframe scrolling and DOM visibility issue."""

	print('Starting iframe scrolling debug test...')

	# Create the sequence of actions for the mock LLM
	# We need to format these as the LLM would return them
	actions = [
		# First action: Navigate to the test URL
		"""
		{
			"thinking": "Navigating to the iframe test page",
			"evaluation_previous_goal": null,
			"memory": "Starting test",
			"next_goal": "Navigate to the iframe test page",
			"action": [
				{
					"go_to_url": {
						"url": "https://browser-use.github.io/stress-tests/challenges/iframe-inception-level1.html",
						"new_tab": false
					}
				}
			]
		}
		""",
		# Second action: Input text in the first name field (to verify we can interact)
		"""
		{
			"thinking": "Inputting text in the first name field to test interaction",
			"evaluation_previous_goal": "Successfully navigated to the page",
			"memory": "Page loaded with nested iframes",
			"next_goal": "Type text in the first name field",
			"action": [
				{
					"input_text": {
						"index": 1,
						"text": "TestName"
					}
				}
			]
		}
		""",
		# Third action: Scroll the iframe (element_index=2 should be the iframe)
		"""
		{
			"thinking": "Scrolling inside the iframe to reveal lower form elements",
			"evaluation_previous_goal": "Successfully typed in first name field",
			"memory": "Typed TestName in first field",
			"next_goal": "Scroll inside the innermost iframe to see more form fields",
			"action": [
				{
					"scroll": {
						"down": true,
						"num_pages": 1.0,
						"index": 2
					}
				}
			]
		}
		""",
		# Fourth action: Done
		"""
		{
			"thinking": "Completed scrolling, ready to inspect DOM",
			"evaluation_previous_goal": "Successfully scrolled inside iframe",
			"memory": "Scrolled to reveal lower form fields",
			"next_goal": "Task completed",
			"action": [
				{
					"done": {
						"text": "Scrolling completed",
						"success": true
					}
				}
			]
		}
		""",
	]

	# Create mock LLM with our action sequence
	mock_llm = create_mock_llm(actions=actions)

	# Create browser session with headless=False so we can see what's happening
	browser_session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=False,  # Set to False to see the browser
			user_data_dir=None,  # Use temporary directory
			keep_alive=True,
			enable_default_extensions=True,
			cross_origin_iframes=True,  # Enable cross-origin iframe support
		)
	)

	try:
		# Start the browser session
		await browser_session.start()
		print('Browser session started')

		# Create an agent with the mock LLM
		agent = Agent(
			task='Navigate to the iframe test page and scroll inside the iframe',
			llm=mock_llm,
			browser_session=browser_session,
		)

		# Helper function to capture and analyze DOM state
		async def capture_dom_state(label: str) -> dict:
			"""Capture DOM state and return analysis"""
			print(f'\n📸 Capturing DOM state: {label}')
			state_event = browser_session.event_bus.dispatch(
				BrowserStateRequestEvent(
					include_dom=True, include_screenshot=False, cache_clickable_elements_hashes=True, include_recent_events=False
				)
			)
			browser_state = await state_event.event_result()

			if browser_state and browser_state.dom_state and browser_state.dom_state.selector_map:
				selector_map = browser_state.dom_state.selector_map
				element_count = len(selector_map)

				# Check for specific elements
				found_elements = {}
				expected_checks = [
					('First Name', ['firstName', 'first name']),
					('Last Name', ['lastName', 'last name']),
					('Email', ['email']),
					('City', ['city']),
					('State', ['state']),
					('Zip', ['zip', 'zipCode']),
				]

				for name, keywords in expected_checks:
					for index, element in selector_map.items():
						element_str = str(element).lower()
						if any(kw.lower() in element_str for kw in keywords):
							found_elements[name] = True
							break

				return {
					'label': label,
					'total_elements': element_count,
					'found_elements': found_elements,
					'selector_map': selector_map,
				}
			return {'label': label, 'error': 'No DOM state available'}

		# Capture initial state before any actions
		print('\n' + '=' * 80)
		print('PHASE 1: INITIAL PAGE LOAD')
		print('=' * 80)

		# Navigate to the page first
		from browser_use.controller.service import Controller

		controller = Controller()

		# Create the action model for navigation
		goto_action = ActionModel.model_validate_json(actions[0])
		await controller.act(goto_action, browser_session)
		await asyncio.sleep(2)  # Wait for page to fully load

		initial_state = await capture_dom_state('INITIAL (after page load)')

		# Now run the rest of the actions via the agent
		print('\n' + '=' * 80)
		print('PHASE 2: EXECUTING ACTIONS')
		print('=' * 80)

		# Create new agent with remaining actions
		remaining_actions = actions[1:]  # Skip the navigation we already did
		mock_llm_remaining = create_mock_llm(actions=remaining_actions)
		agent = Agent(
			task='Input text and scroll inside the iframe',
			llm=mock_llm_remaining,
			browser_session=browser_session,
		)

		# Hook into agent actions to capture state after each one
		states = []
		original_act = controller.act

		async def wrapped_act(action, session):
			result = await original_act(action, session)
			# Capture state after each action
			action_type = 'unknown'
			if hasattr(action, 'input_text') and action.input_text:
				action_type = 'input_text'
				await asyncio.sleep(1)  # Give time for DOM to update
				state = await capture_dom_state('AFTER INPUT_TEXT')
				states.append(state)
			elif hasattr(action, 'scroll') and action.scroll:
				action_type = 'scroll'
				await asyncio.sleep(2)  # Give more time after scroll
				state = await capture_dom_state('AFTER SCROLL')
				states.append(state)
			return result

		controller.act = wrapped_act

		# Run the agent with remaining actions
		result = await agent.run()
		print(f'\nAgent completed with result: {result}')

		# Analyze all captured states
		print('\n' + '=' * 80)
		print('PHASE 3: ANALYSIS OF DOM STATES')
		print('=' * 80)

		all_states = [initial_state] + states

		for state in all_states:
			if 'error' in state:
				print(f'\n❌ {state["label"]}: {state["error"]}')
			else:
				print(f'\n📊 {state["label"]}:')
				print(f'  Total elements: {state["total_elements"]}')
				print('  Found elements:')
				for elem_name, found in state['found_elements'].items():
					status = '✓' if found else '✗'
					print(f'    {status} {elem_name}')

		# Compare states
		print('\n' + '=' * 80)
		print('COMPARISON SUMMARY')
		print('=' * 80)

		if len(all_states) >= 3:
			initial = all_states[0]
			after_input = all_states[1] if len(all_states) > 1 else None
			after_scroll = all_states[2] if len(all_states) > 2 else None

			print('\nElement count changes:')
			print(f'  Initial: {initial.get("total_elements", 0)} elements')
			if after_input:
				print(f'  After input_text: {after_input.get("total_elements", 0)} elements')
			if after_scroll:
				print(f'  After scroll: {after_scroll.get("total_elements", 0)} elements')

			# Check if lower form fields appear after scroll
			if after_scroll and 'found_elements' in after_scroll:
				lower_fields = ['City', 'State', 'Zip']
				missing_fields = [f for f in lower_fields if not after_scroll['found_elements'].get(f, False)]

				if missing_fields:
					print('\n⚠️  BUG CONFIRMED: Lower form fields missing after scroll:')
					for field in missing_fields:
						print(f'    ✗ {field}')
					print('\nThis confirms that scrolling inside iframes does not update the DOM tree properly.')
				else:
					print('\n✅ SUCCESS: All lower form fields are visible after scrolling!')

		# Show first few elements from final state for debugging
		if states and 'selector_map' in states[-1]:
			print('\n' + '=' * 80)
			print('DEBUG: First 5 elements in final selector_map')
			print('=' * 80)
			final_map = states[-1]['selector_map']
			for i, (index, element) in enumerate(list(final_map.items())[:5]):
				elem_preview = str(element)[:150]
				print(f'\n  [{index}]: {elem_preview}...')

		# Keep browser open for manual inspection if needed
		print('\n' + '=' * 80)
		print('Test complete. Browser will remain open for 10 seconds for inspection...')
		print('=' * 80)
		await asyncio.sleep(10)

	finally:
		# Clean up
		print('\nCleaning up...')
		await browser_session.kill()
		await browser_session.event_bus.stop(clear=True, timeout=5)
		print('Browser session closed')


if __name__ == '__main__':
	# Run the debug test
	asyncio.run(debug_iframe_scrolling())
