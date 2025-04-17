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
		Go to techcrunch.com and perform the following tasks:
		1. Browse the homepage and save at least 3 interesting article headlines and their brief descriptions to memory in the "tech_news" category.
		2. Click on one of the articles that interests you and read it. Save key points from the article to memory in the "article_details" category.
		3. Use the memory_list action to verify what you've saved so far.
		4. Go back to the homepage and find another article on a different topic. Save information about this article in the "tech_news" category.
		5. Use memory_retrieve to search for information related to a specific technology or company mentioned in any of the articles.
		6. Summarize what you've learned from all the articles based on the memories you've saved.
		7. Delete one of the memories you created and verify it was removed.
		""",
		llm=llm,
		max_actions_per_step=1,
		browser=browser,
		enable_memory=True,
		memory_interval=15,
	)

	await agent.run(max_steps=30)


if __name__ == '__main__':
	asyncio.run(run_memory_test())
