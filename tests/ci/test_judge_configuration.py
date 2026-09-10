"""Tests for configurable judge screenshot budgets."""

import pytest
from pydantic import ValidationError

from browser_use.agent.service import Agent
from tests.ci.conftest import create_mock_llm


def test_agent_configures_judge_max_images() -> None:
	agent = Agent(task='Test task', llm=create_mock_llm(), judge_max_images=3)

	assert agent.settings.judge_max_images == 3


def test_agent_rejects_empty_judge_image_budget() -> None:
	with pytest.raises(ValidationError):
		Agent(task='Test task', llm=create_mock_llm(), judge_max_images=0)
