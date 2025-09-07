import asyncio
import os
import sys

# Add the parent directory to the path so we can import browser_use
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()


from browser_use import Agent, BrowserProfile

# Speed optimization instructions for the model
SPEED_OPTIMIZATION_PROMPT = """
Speed optimization instructions:
- Be extremely concise and direct in your responses
- Get to the goal as quickly as possible
- Use multi-action sequences whenever possible to reduce steps
"""


async def main():
	# 1. Use fast LLM - Llama 4 on Groq for ultra-fast inference
	from browser_use import ChatGroq

	llm = ChatGroq(
		model='meta-llama/llama-4-maverick-17b-128e-instruct',
		temperature=0.0,
	)
	# from browser_use import ChatGoogle

	# llm = ChatGoogle(model='gemini-2.5-flash')

	# 2. Create speed-optimized browser profile
	browser_profile = BrowserProfile(
		minimum_wait_page_load_time=0.1,
		wait_between_actions=0.1,
		headless=False,
	)

	# 3. Define a speed-focused task
	task = """
	1. Go to reddit https://www.reddit.com/search/?q=browser+agent&type=communities 
	2. Click directly on the first 5 communities to open each in new tabs
    3. Find out what the latest post is about, and switch directly to the next tab
	4. Return the latest post summary for each page
	"""

	# 4. Create agent with all speed optimizations
	agent = Agent(
		task=task,
		llm=llm,
		flash_mode=True,  # Disables thinking in the LLM output for maximum speed
		browser_profile=browser_profile,
		extend_system_message=SPEED_OPTIMIZATION_PROMPT,
	)

	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
