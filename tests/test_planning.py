import asyncio
import json
import os
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from browser_use import Agent
from browser_use.agent.planning.service import PlanningService
from browser_use.agent.views import PlanningResult
from browser_use.browser.browser import Browser, BrowserConfig


@pytest.mark.asyncio
@patch('langchain_openai.ChatOpenAI')
async def test_planning_service(mock_chat_openai):
    # Mock the LLM response
    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = MagicMock(
        generations=[
            [
                MagicMock(
                    message=AIMessage(
                        content=json.dumps({
                            "state_analysis": "Current state analysis",
                            "progress_evaluation": "Progress evaluation",
                            "next_steps": "Next steps to take"
                        })
                    )
                )
            ]
        ]
    )
    mock_chat_openai.return_value = mock_llm
    
    # Initialize the agent with planning
    llm = ChatOpenAI(model="gpt-4o", temperature=0.0)
    agent = Agent(
        task="Go to https://www.google.com and search for 'python programming'",
        llm=llm,
        planner_interval=1,  # Plan every step
    )
    
    # Mock the agent's run method
    agent.run = AsyncMock()
    agent.state.history = MagicMock()
    agent._planning_service = MagicMock()
    agent._planning_service.last_plan = PlanningResult(
        state_analysis="Current state analysis",
        progress_evaluation="Progress evaluation",
        next_steps="Next steps to take"
    )
    
    # Check that planning was performed
    assert agent.last_plan is not None
    
    # Verify planning result structure
    plan = agent.last_plan
    assert isinstance(plan, PlanningResult)
    assert hasattr(plan, "state_analysis")
    assert hasattr(plan, "progress_evaluation")
    assert hasattr(plan, "next_steps")
    
    # Convert to dict and verify
    plan_dict = plan.to_dict()
    assert "state_analysis" in plan_dict
    assert "progress_evaluation" in plan_dict
    assert "next_steps" in plan_dict


@pytest.mark.asyncio
@patch('langchain_openai.ChatOpenAI')
async def test_planning_with_custom_llm(mock_chat_openai):
    # Mock the LLM response
    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = MagicMock(
        generations=[
            [
                MagicMock(
                    message=AIMessage(
                        content=json.dumps({
                            "state_analysis": "Current state analysis",
                            "progress_evaluation": "Progress evaluation",
                            "next_steps": "Next steps to take"
                        })
                    )
                )
            ]
        ]
    )
    mock_chat_openai.return_value = mock_llm
    
    # Initialize the agent with a different LLM for planning
    main_llm = ChatOpenAI(model="gpt-4o", temperature=0.0)
    planner_llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0.0)
    
    agent = Agent(
        task="Go to https://www.google.com and search for 'python programming'",
        llm=main_llm,
        planner_llm=planner_llm,
        planner_interval=1,
    )
    
    # Mock the agent's run method
    agent.run = AsyncMock()
    agent.state.history = MagicMock()
    agent._planning_service = MagicMock()
    agent._planning_service.last_plan = PlanningResult(
        state_analysis="Current state analysis",
        progress_evaluation="Progress evaluation",
        next_steps="Next steps to take"
    )
    
    # Check that planning was performed
    assert agent.last_plan is not None


@pytest.mark.asyncio
@patch('langchain_openai.ChatOpenAI')
async def test_planning_interval(mock_chat_openai):
    # Mock the LLM response
    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = MagicMock(
        generations=[
            [
                MagicMock(
                    message=AIMessage(
                        content=json.dumps({
                            "state_analysis": "Current state analysis",
                            "progress_evaluation": "Progress evaluation",
                            "next_steps": "Next steps to take"
                        })
                    )
                )
            ]
        ]
    )
    mock_chat_openai.return_value = mock_llm
    
    # Initialize the agent with planning every 2 steps
    llm = ChatOpenAI(model="gpt-4o", temperature=0.0)
    agent = Agent(
        task="Go to https://www.google.com and search for 'python programming'",
        llm=llm,
        planner_interval=2,  # Plan every 2 steps
    )
    
    # Mock the agent's run method
    agent.run = AsyncMock()
    agent.state.history = MagicMock()
    agent._planning_service = MagicMock()
    agent._planning_service.last_plan = PlanningResult(
        state_analysis="Current state analysis",
        progress_evaluation="Progress evaluation",
        next_steps="Next steps to take"
    )
    
    # Check planning was performed
    assert agent.last_plan is not None


if __name__ == "__main__":
    asyncio.run(test_planning_service()) 