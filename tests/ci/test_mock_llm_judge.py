import pytest

from browser_use import Agent
from browser_use.agent.views import JudgementResult
from browser_use.llm.messages import UserMessage
from tests.ci.conftest import create_mock_llm


@pytest.mark.asyncio
async def test_create_mock_llm_supports_judgement_output():
	llm = create_mock_llm()

	response = await llm.ainvoke([UserMessage(content='Judge this trace')], output_format=JudgementResult)

	assert response.completion.verdict is True
	assert response.completion.failure_reason == ''
	assert response.completion.impossible_task is False


@pytest.mark.asyncio
async def test_agent_run_with_mock_llm_attaches_judgement(browser_session):
	agent = Agent(
		task='Complete the task immediately.',
		llm=create_mock_llm(),
		browser_session=browser_session,
		use_judge=True,
	)

	history = await agent.run(max_steps=1)

	assert history.is_done() is True
	assert history.is_judged() is True
	assert history.is_validated() is True
	assert history.judgement() == {
		'reasoning': 'Mock judge verified that the task was completed successfully.',
		'verdict': True,
		'failure_reason': '',
		'impossible_task': False,
		'reached_captcha': False,
	}
