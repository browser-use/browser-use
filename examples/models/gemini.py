import asyncio
import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr
import lucidicai as lai
from browser_use import Agent, BrowserConfig
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContextConfig

load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
	raise ValueError('GEMINI_API_KEY is not set')

llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(api_key))

browser = Browser(
	config=BrowserConfig(
		new_context_config=BrowserContextConfig(
			viewport_expansion=0,
			highlight_elements=False,
		)
	)
)

task = "Go to Google Maps, search for Itaian restaurants in San Francisco, and go the website of a good one. Then, go to Google Maps again, search for French restaurants in San Francisco, and go to the website of a good one."

lai.init(
	"Gemini Restaurant Research",
	task=task,
	# mass_sim_id="84b01bb7-8fff-4c19-b1f9-4cbc2f8f3f1a"
)

async def run_search():
	agent = Agent(
		task=task,
		llm=llm,
		max_actions_per_step=4,
		browser=browser,
	)
	handler = lai.LucidicLangchainHandler()
	handler.attach_to_llms(agent)

	await agent.run(max_steps=25)


if __name__ == '__main__':
	asyncio.run(run_search())
