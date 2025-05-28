"""
Test dropdown interaction functionality.
"""

import pytest

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentHistoryList


async def test_dropdown(llm, browser_session):
	"""Test selecting an option from a dropdown menu."""
	agent = Agent(
		task=(
			'go to https://codepen.io/geheimschriftstift/pen/mPLvQz and first get all options for the dropdown and then select the 5th option'
		),
		llm=llm,
		browser_session=browser_session,
	)

	try:
		history: AgentHistoryList = await agent.run(20)
		result = history.final_result()

		# Verify dropdown interaction
		assert result is not None
		assert 'Duck' in result, "Expected 5th option 'Duck' to be selected"

		# Verify dropdown state
		page = await browser_session.get_current_page()
		element = await page.query_selector('select')
		assert element is not None, 'Dropdown element should exist'

		value = await element.evaluate('el => el.value')
		assert value == '5', 'Dropdown should have 5th option selected'

	except Exception as e:
		pytest.fail(f'Dropdown test failed: {str(e)}')
