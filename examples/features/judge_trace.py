"""
Setup:
1. Get your API key from https://cloud.browser-use.com/new-api-key
2. Set environment variable: export BROWSER_USE_API_KEY="your-key"
"""

import asyncio
import os
import sys

# Add the parent directory to the path so we can import browser_use
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent
from browser_use.llm.browser_use.chat import ChatBrowserUse

# task from GAIA
task = """
If Eliud Kipchoge could maintain his record-making marathon pace indefinitely, how many thousand hours would it take him to run the distance between the Earth and the Moon its closest approach? 
Please use the minimum perigee value on the Wikipedia page for the Moon when carrying out your calculation. 
Round your result to the nearest 1000 hours and do not use any comma separators if necessary.
"""


async def main():
	llm = ChatBrowserUse()
	agent = Agent(
		task=task,
		llm=llm,
		use_judge=True,
		judge_llm=llm,
		ground_truth='16',  # The TRUE answer is 17 but we put 16 to demonstrate judge can detect when the answer is wrong.
	)
	history = await agent.run()

	# Get the judgement result
	if history.is_judged():
		judgement = history.judgement()
		print(f'Agent history judgement: {judgement}')


if __name__ == '__main__':
	asyncio.run(main())
