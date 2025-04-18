import asyncio
import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr

from browser_use import Agent, BrowserConfig
from browser_use.browser.browser import Browser

load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
	raise ValueError('GEMINI_API_KEY is not set')

llm = ChatGoogleGenerativeAI(model='gemini-2.0-flash', api_key=SecretStr(api_key))

browser = Browser(
	config=BrowserConfig(
		browser_binary_path='/usr/bin/google-chrome',
	)
)


async def run_memory_test():
	agent = Agent(
		task="""
			Go to news.ycombinator.com and perform the following tasks:
			1. Browse the homepage and save one interesting article headline to memory in the "tech_news" category.
			2. Save a milestone to memory in the "milestones" category with the message "Completed article selection".
			3. Use the memory_retrieve action to check if the milestone "Completed article selection" exists. If it exists, continue to the next step. If not, repeat steps 1-2.
			4. Click on the article you saved and read it. Save one key point from the article to memory in the "article_details" category.
			5. Save a milestone to memory in the "milestones" category with the message "Completed article reading".
			6. Use memory_retrieve to check if the milestone "Completed article reading" exists. If it exists, continue to the next step. If not, repeat steps 4-5.
			7. Use memory_list action to verify what you've saved so far.
			8. Summarize what you've learned from the article based on the memories you've saved.
		""",
		llm=llm,
		max_actions_per_step=1,
		browser=browser,
		enable_memory=True,
	)

	await agent.run(max_steps=30)


if __name__ == '__main__':
	asyncio.run(run_memory_test())
