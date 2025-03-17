import os
import sys
from pathlib import Path

from browser_use.agent.views import ActionResult

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from pydantic import SecretStr
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from playwright.async_api import BrowserContext

browser = Browser(config=BrowserConfig(chrome_instance_path='/usr/bin/google-chrome-stable',))
prompt = """
- Go to https://pro-app.peek.com/-/activities. If necessary, log in with username vikram@elvity.ai and password 'udk.VBE2pex1zmj.mcp'. 
- Click on the new Activity Button.
- Set the name of activity to butest7 and the description to 'butest7 desc'. 
- Clear the Total Price Field . 
- Enter 15 as the new value. 
- Clear the Ticket name field which contains the word 'Adult' and replace it with the word 'Senior'. 
- Click on "+ Add Another" . 
- Clear the ticket name field that contains the word Adult and replace it with the word 'Kids'. 
- Then change the price of kids ticket from 10 to 8
- In the Max Guests section, click on Other and enter 7
"""

async def main():
        context = await browser.new_context()
        while True:
                user_input = input("Enter instruction (or 'exit' to stop): ")
                if user_input.lower() == 'exit':
                        print("Exiting the loop.")
                        break
                agent = Agent(
                        max_actions_per_step=2,
                        task=user_input,
                        llm=ChatGoogleGenerativeAI(model='gemini-2.0-flash', api_key=SecretStr(os.getenv('GEMINI_API_KEY', ''))),
                        browser_context=context
                )
                await agent.run()


if __name__ == '__main__':
        asyncio.run(main())
