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
    GOOGLE_CREDENTIALS_JSON must be set in .env with the path to google's credentials.json file.
    """
    # Replace with your actual spreadsheet URL.
    spreadsheet_url = "https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit"
    
    # Each action now expects at least the 'url'. (If you want to use a sheet
    # other than the default "Sheet1", include a "sheet_name" parameter.)
    initial_actions = [
        {"open_google_spreadsheet": {"url": spreadsheet_url}},
        {"insert_value": {"url": spreadsheet_url, "cell": "C2", "value": "3"}},
        {"insert_value": {"url": spreadsheet_url, "cell": "D2", "value": "5"}},
        {"insert_function": {"url": spreadsheet_url, "cell": "E2", "function": "=SUM(C2:D2)"}},
        {"add_row": {"url": spreadsheet_url}},
        {"delete_row": {"url": spreadsheet_url, "row": 2}},
    ]
    
    # Set up the browser context.
    context = BrowserContext(
        browser=Browser(config=BrowserConfig(headless=False, disable_security=True))
    )
    
    # Create the agent with the task.
    agent = Agent(
        task=f"""
        1. Open the spreadsheet {spreadsheet_url} and insert values: Tesla in A1, Meta in A2 and Microsoft in A3.
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
