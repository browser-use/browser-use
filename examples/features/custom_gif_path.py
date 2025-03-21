import asyncio
import os
from pydantic import SecretStr
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from browser_use import Agent, BrowserConfig, ActionResult, Controller
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContextConfig, BrowserContextWindowSize

load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
	raise ValueError('GEMINI_API_KEY is not set')

controller = Controller()

llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash-exp', api_key=SecretStr(api_key))


browser = Browser(
	config=BrowserConfig(
		new_context_config=BrowserContextConfig(
			viewport_expansion=0,
			no_viewport=False,
			browser_window_size=BrowserContextWindowSize(width=1280, height=1000),
		),
		headless=False,
	)
)

agent = Agent(
    task='Find the founders of browser-use and draft them a short personalized message',
    llm=llm,
    controller=controller,
    max_actions_per_step=10,
    browser=browser,
    use_vision=False,
    generate_gif=True,
    gif_output_path='test_agent.gif',	
)

async def main():
	await agent.run(max_steps=25)	


if __name__ == '__main__':
	asyncio.run(main())
