"""Tests that _run_simple_judge does not corrupt structured output JSON.

Regression test for https://github.com/browser-use/browser-use/issues/4103
When output_model_schema is set, _run_simple_judge must not append text
to extracted_content because that would break model_validate_json().
"""

import json
from unittest.mock import AsyncMock

from pydantic import BaseModel, Field

from browser_use.agent.service import Agent
from browser_use.agent.views import (
	ActionResult,
	AgentHistory,
	AgentHistoryList,
	BrowserStateHistory,
	SimpleJudgeResult,
)
from browser_use.llm.views import ChatInvokeCompletion
from tests.ci.conftest import create_mock_llm


class ContactList(BaseModel):
	"""Example structured output schema for testing."""

	contacts: list[str] = Field(default_factory=list, description='List of contact names')


def _make_done_result(extracted_content: str) -> ActionResult:
	"""Create a done ActionResult with given extracted_content."""
	return ActionResult(
		is_done=True,
		success=True,
		extracted_content=extracted_content,
	)


def _make_history(result: ActionResult) -> AgentHistoryList:
	"""Wrap a single ActionResult into a minimal AgentHistoryList."""
	return AgentHistoryList(
		history=[
			AgentHistory(
				model_output=None,
				result=[result],
				state=BrowserStateHistory(url='about:blank', title='', tabs=[], interacted_element=[]),
			)
		]
	)


async def test_judge_rejection_preserves_structured_json():
	"""When output_model_schema is set and judge rejects, extracted_content must remain valid JSON."""
	structured_json = json.dumps({'contacts': ['Alice', 'Bob']})

	# Set up agent with output_model_schema
	llm = create_mock_llm()
	agent = Agent(task='Extract contacts', llm=llm, output_model_schema=ContactList)

	# Manually build history as if the agent had completed with structured output
	done_result = _make_done_result(structured_json)
	agent.history = _make_history(done_result)

	# Mock the LLM to return a judge rejection on the next call
	async def judge_ainvoke(*args, **kwargs):
		judge = SimpleJudgeResult(is_correct=False, reason='Task requirements not fully met')
		return ChatInvokeCompletion(completion=judge, usage=None)

	agent.llm.ainvoke = AsyncMock(side_effect=judge_ainvoke)

	# Run the simple judge
	await agent._run_simple_judge()

	# extracted_content must still be valid JSON parseable by the output model
	last = agent.history.history[-1].result[-1]
	parsed = ContactList.model_validate_json(last.extracted_content)
	assert parsed.contacts == ['Alice', 'Bob'], 'Structured output should remain intact'

	# Judge note should be stored separately in judge_note field
	assert last.judge_note is not None
	assert 'not fully met' in last.judge_note

	# Success should be overridden to False
	assert last.success is False


async def test_judge_rejection_appends_to_plain_text():
	"""Without output_model_schema, the judge should append its note to extracted_content."""
	llm = create_mock_llm()
	agent = Agent(task='Extract contacts', llm=llm)

	done_result = _make_done_result('Here are the contacts: Alice, Bob')
	agent.history = _make_history(done_result)

	async def judge_ainvoke(*args, **kwargs):
		judge = SimpleJudgeResult(is_correct=False, reason='Incomplete result')
		return ChatInvokeCompletion(completion=judge, usage=None)

	agent.llm.ainvoke = AsyncMock(side_effect=judge_ainvoke)

	await agent._run_simple_judge()

	last = agent.history.history[-1].result[-1]
	# In plain-text mode, the note should be appended to extracted_content
	assert '[Simple judge: Incomplete result]' in last.extracted_content
	assert 'Here are the contacts' in last.extracted_content
	# judge_note should also be populated
	assert last.judge_note is not None
	assert 'Incomplete result' in last.judge_note
	assert last.success is False


async def test_judge_approval_leaves_content_untouched():
	"""When the judge approves (is_correct=True), nothing should be modified."""
	structured_json = json.dumps({'contacts': ['Alice']})

	llm = create_mock_llm()
	agent = Agent(task='Extract contacts', llm=llm, output_model_schema=ContactList)

	done_result = _make_done_result(structured_json)
	agent.history = _make_history(done_result)

	async def judge_ainvoke(*args, **kwargs):
		judge = SimpleJudgeResult(is_correct=True, reason='')
		return ChatInvokeCompletion(completion=judge, usage=None)

	agent.llm.ainvoke = AsyncMock(side_effect=judge_ainvoke)

	await agent._run_simple_judge()

	last = agent.history.history[-1].result[-1]
	assert last.extracted_content == structured_json
	assert last.success is True
	# No judge note should be set when approved
	assert last.judge_note is None


async def test_judge_skips_when_not_done():
	"""_run_simple_judge should be a no-op when is_done is False."""
	llm = create_mock_llm()
	agent = Agent(task='Test', llm=llm)

	result = ActionResult(is_done=False, success=None, extracted_content='some content')
	agent.history = _make_history(result)

	agent.llm.ainvoke = AsyncMock()

	await agent._run_simple_judge()

	# LLM should never have been called
	agent.llm.ainvoke.assert_not_called()
	assert result.extracted_content == 'some content'


async def test_judge_skips_when_agent_reports_failure():
	"""_run_simple_judge should be a no-op when the agent already reports failure."""
	llm = create_mock_llm()
	agent = Agent(task='Test', llm=llm)

	result = ActionResult(is_done=True, success=False, extracted_content='failed')
	agent.history = _make_history(result)

	agent.llm.ainvoke = AsyncMock()

	await agent._run_simple_judge()

	agent.llm.ainvoke.assert_not_called()
	assert result.extracted_content == 'failed'
