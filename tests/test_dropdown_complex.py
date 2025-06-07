"""
Test complex dropdown interaction functionality.
"""

import pytest

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList


async def test_dropdown_complex(llm, browser_session):
	"""Test selecting an option from a complex dropdown menu."""
	agent = Agent(
		task=(
			'go to https://codepen.io/shyam-king/pen/pvzpByJ and first get all options for the dropdown and then select the json option'
		),
		llm=llm,
		browser_session=browser_session,
	)

	try:
		history: AgentHistoryList = await agent.run(20)
		result = history.final_result()

		# Verify dropdown interaction
		assert result is not None
		assert 'json' in result.lower(), "Expected 'json' option to be selected"

		# Verify dropdown state
		page = await browser_session.get_current_page()
		element = await page.query_selector('.select-selected')
		assert element is not None, 'Custom dropdown element should exist'

		text = await element.text_content()
		assert 'json' in text.lower(), 'Dropdown should display json option'

		# Verify the selected option's effect
		code_element = await page.query_selector('pre code')
		assert code_element is not None, 'Code element should be visible when JSON is selected'

	except Exception as e:
		pytest.fail(f'Complex dropdown test failed: {str(e)}')
