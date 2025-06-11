# Goal: A general-purpose web navigation agent for tasks like flight booking and course searching.

import asyncio
import os
import sys

# Adjust Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import AzureChatOpenAI, ChatOpenAI
from pydantic import SecretStr

from browser_use.agent.service import Agent
from browser_use.browser import BrowserProfile, BrowserSession

# Set LLM based on defined environment variables
if os.getenv('OPENAI_API_KEY'):
	llm = ChatOpenAI(
		model='gpt-4o',
	)
elif os.getenv('AZURE_OPENAI_KEY') and os.getenv('AZURE_OPENAI_ENDPOINT'):
	llm = AzureChatOpenAI(
		model='gpt-4o',
		api_version='2024-10-21',
		azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT', ''),
		api_key=SecretStr(os.getenv('AZURE_OPENAI_KEY', '')),
	)
else:
	raise ValueError('No LLM found. Please set OPENAI_API_KEY or AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT.')


browser_session = BrowserSession(
	browser_profile=BrowserProfile(
		headless=False,  # This is True in production
		minimum_wait_page_load_time=1,  # 3 on prod
		maximum_wait_page_load_time=10,  # 20 on prod
		viewport={'width': 1280, 'height': 1100},
		user_data_dir='~/.config/browseruse/profiles/default',
		# trace_path='./tmp/web_voyager_agent',
	)
)

# TASK = """
# Find the lowest-priced one-way flight from Cairo to Montreal on February 21, 2025, including the total travel time and number of stops. on https://www.google.com/travel/flights/
# """
# TASK = """
# Browse Coursera, which universities offer Master of Advanced Study in Engineering degrees? Tell me what is the latest application deadline for this degree? on https://www.coursera.org/"""
TASK = """
Find and book a hotel in Paris with suitable accommodations for a family of four (two adults and two children) offering free cancellation for the dates of February 14-21, 2025. on https://www.booking.com/
"""


async def main():
	agent = Agent(
		task=TASK,
		llm=llm,
		browser_session=browser_session,
		validate_output=True,
		enable_memory=False,
	)
	history = await agent.run(max_steps=50)
	history.save_to_file('./tmp/history.json')


if __name__ == '__main__':
	asyncio.run(main())
