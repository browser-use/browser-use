import os
import sys
import asyncio

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    
import pytest
from dotenv import load_dotenv

# Third-party imports
from langchain_openai import ChatOpenAI

# Local imports
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext
from browser_use import Agent, Controller
from browser_use.agent.views import AgentHistoryList

# Load environment variables.
load_dotenv()

# Initialize language model and controller.
llm = ChatOpenAI(model='gpt-4o')
controller = Controller()


@pytest.mark.skip(reason="This is for local testing only")
async def test_evaluate_code_agent():
    """Test the evaluate_code functionality via an agent."""
    # Define initial actions to open a tab and then execute evaluate_code.
    initial_actions = [
        {"open_tab": {"url": "https://pypi.org/"}},
        # {"evaluate_js": {"code": "() => alert('Hello')"}}
    ]

    # Set up the browser context.
    context = BrowserContext(
        browser=Browser(config=BrowserConfig(headless=False, disable_security=True)),
    )

    # Create the agent with the task.
    agent = Agent(
        task="Evaluate the js code alert('test') on PyPI website using evaluate_js action.",
        llm=llm,
        browser_context=context,
        initial_actions=initial_actions,
        controller=controller
    )

    # Run the agent for a few steps to trigger navigation and then the evaluate_code action.
    history: AgentHistoryList = await agent.run(max_steps=3)
    action_names = history.action_names()

    # Ensure that the evaluate_code action was executed.
    assert "evaluate_js" in action_names, "Expected evaluate_js action to be executed."

    await context.close()


@pytest.mark.skip(reason="This is for local testing only")
async def test_hover_element_agent():
    """Test the hover_element_action functionality via an agent."""
    # Define initial actions to open a tab and then invoke the hover element action.
    initial_actions = [
        {"open_tab": {"url": "https://practice.expandtesting.com/hovers#google_vignette"}},
        # {"hover_element": {"index": 0, "xpath": "/html/body/main/div[3]/div/div[1]"}}
    ]

    # Set up the browser context.
    context = BrowserContext(
        browser=Browser(config=BrowserConfig(headless=False, disable_security=True)),
    )

    # Create the agent with the task.
    agent = Agent(
        task="Hover over the first user image on the page (body > main > div.page-layout > div > div:nth-child(4)) and wait for 5 seconds.",
        llm=llm,
        browser_context=context,
        initial_actions=initial_actions,
        controller=controller
    )

    # Run the agent for a few steps to trigger navigation and then the hover_element action.
    history: AgentHistoryList = await agent.run(max_steps=3)
    action_names = history.action_names()

    # Ensure that the hover_element action was executed.
    assert "hover_element" in action_names, "Expected hover_element action to be executed."

    # Verify that the tooltip text becomes visible after hovering.
    page = await context.get_current_page()
    # On this page, the tooltip text is within an element with class "tooltiptext" inside the element with class "tooltip".
    event_log = page.get_by_text('mouseover    type=Element id=red')
    assert event_log is not None, "Expected to find the event log to be on the page."
    is_visible = await event_log.is_visible()
    assert is_visible, "Expected the event log to be visible after hovering."

    await context.close()


if __name__ == '__main__':
    asyncio.run(test_evaluate_code_agent())
    asyncio.run(test_hover_element_agent())
