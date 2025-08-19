"""
Getting Started Example 3: Data Extraction

This example demonstrates how to:
- Navigate to a website with structured data
- Extract specific information from the page
- Process and organize the extracted data
- Return structured results

This builds on previous examples by showing how to get valuable data from websites.
"""

import asyncio
import os
import sys

# Add the parent directory to the path so we can import browser_use
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, ChatOpenAI


async def main():
	# Initialize the model
	llm = ChatOpenAI(model='gpt-4.1-mini')

	# Define a data extraction task
	task = """
    Go to https://quotes.toscrape.com/ and extract the following information:
    - The first 5 quotes on the page
    - The author of each quote
    - The tags associated with each quote
    
    Present the information in a clear, structured format like:
    Quote 1: "[quote text]" - Author: [author name] - Tags: [tag1, tag2, ...]
    Quote 2: "[quote text]" - Author: [author name] - Tags: [tag1, tag2, ...]
    etc.
    """

	# Create and run the agent
	agent = Agent(task=task, llm=llm)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
