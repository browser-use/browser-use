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
async def test_google_spreadsheet_actions_agent():
    """
    Test the Google Spreadsheet actions via an agent.

    This test performs the following actions:
      1. Opens a Google Spreadsheet.
      2. Inserts a value into cell B2.
      3. Inserts a function into cell C3.
      4. Updates a range starting at D2 with multiple values.
      5. Adds a new row.
      6. Deletes row 4.

    Since the Google Sheets UI does not expose cell coordinates as simple aria-labels,
    we verify that the expected text ("Test Value") appears somewhere in a gridcell.
    """
    # Replace with your actual spreadsheet URL.
    spreadsheet_url = "https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit"
    initial_actions = [
        {"open_google_spreadsheet": {"url": spreadsheet_url}},
        {"insert_value": {"cell": "C2", "value": "3"}},
        {"insert_value": {"cell": "D2", "value": "5"}},
        {"insert_function": {"cell": "E2", "function": "=SUM(C2:D2)"}},
        {"add_row": {}},
        {"delete_row": {"row": 2}},
    ]
    
    # Set up the browser context.
    context = BrowserContext(
        browser=Browser(config=BrowserConfig(headless=False, disable_security=True))
    )
    
    # Create the agent with the task.
    agent = Agent(
        task="""
        1. Write these 3 companies into my Google Sheet: Tesla, Meta, Microsoft.
        2. Read this Google Sheet with a list of companies, do a Google search for the first one, and write the website link back into Google Sheets next to the company name.
        """,
        llm=llm,
        browser_context=context,
        initial_actions=initial_actions,
        controller=controller
    )
    
    # Run the agent for enough steps to execute all actions.
    history: AgentHistoryList = await agent.run()
    action_names = history.action_names()
    
    assert "open_google_spreadsheet" in action_names, "Expected open_google_spreadsheet action to be executed."
    await context.close()


if __name__ == '__main__':
    asyncio.run(test_google_spreadsheet_actions_agent())
