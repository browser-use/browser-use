# Goal: A general-purpose web navigation agent for tasks like flight booking and course searching.

import os
import sys
import asyncio

# Adjust Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pydantic import SecretStr
from langchain_openai import AzureChatOpenAI

from browser_use import BrowserConfig, Agent, Browser
from browser_use import BrowserContextConfig


from supatest import SupatestAgent
from supatest import SupatestBrowser
from supatest import SupatestBrowserContext
# Load environment variables
load_dotenv()

# Validate required environment variables
required_env_vars = ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"]
for var in required_env_vars:
    if not os.getenv(var):
        raise ValueError(f"{var} is not set. Please add it to your environment variables.")

browser = SupatestBrowser(
	config=BrowserConfig(
		headless=False,  # This is True in production
		disable_security=True,
		new_context_config=BrowserContextConfig(
			disable_security=True,
			minimum_wait_page_load_time=1,  # 3 on prod
			maximum_wait_page_load_time=10,  # 20 on prod
			# no_viewport=True,
			browser_window_size={
				'width': 500,
				'height': 1100,
			},
			# trace_path='./tmp/web_voyager_agent',
		),
	)
)
llm = AzureChatOpenAI(
	model='gpt-4o',
	api_version='2024-10-21',
	azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT', ''),
	api_key=SecretStr(os.getenv('AZURE_OPENAI_API_KEY', '')),
)

# TASK = """
# Find the lowest-priced one-way flight from Cairo to Montreal on February 21, 2025, including the total travel time and number of stops. on https://www.google.com/travel/flights/
# """
# TASK = """
# Browse Coursera, which universities offer Master of Advanced Study in Engineering degrees? Tell me what is the latest application deadline for this degree? on https://www.coursera.org/"""
# TASK = """
# Find and book a hotel in Paris with suitable accommodations for a family of four (two adults and two children) offering free cancellation for the dates of February 14-21, 2025. on https://www.booking.com/
# """

# TASK = """
# Go to https://blazedemo.com/index.php and select Boston for departure and London for destination. Then click on Find Flights. Select the first flight and click on Choose This Flight. Then on the next page, scroll down by some amount and just do nothing. Do nothing after that.
# """

# TASK = """
# Go to https://blazedemo.com/index.php and get all dropdown options for departure city and destination city. Then select Boson for departure city and London for destination city. Just do nothing after that.
# """

# TASK = """
# Browse coursera using https://www.coursera.org/ and then seach for IBM AI Developer and search by pressing 'Enter'. Scroll down by 1500 pixels and then up by 500 pixels. Then Go back to coursera homepage and switch to another tab and open coursera homepage again. Search 'full stack developer course' in search bar by pressing 'Enter'.
# """


TASK = """
Go to https://coffee-cart.app/ and click on Expresso and Cappuccino and add them to the cart. Then do nothing.
"""

async def main():
	agent = SupatestAgent(
		task=TASK,
		llm=llm,
		browser=browser,
	)
	history = await agent.run(max_steps=50)
	history.save_to_file('./tmp/history.json')


if __name__ == "__main__":
	asyncio.run(main())
