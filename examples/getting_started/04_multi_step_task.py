"""
Getting Started Example 4: Multi-Step Task

This example demonstrates how to:
- Perform a complex workflow with multiple steps
- Navigate between different pages
- Combine search, form filling, and data extraction
- Handle a realistic end-to-end scenario

This is the most advanced getting started example, combining all previous concepts.
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

	# Define a multi-step task
	task = """
    I want you to research Python web scraping libraries. Here's what I need:
    
    1. First, search Google for "best Python web scraping libraries 2024"
    2. Find a reputable article or blog post about this topic
    3. From that article, extract the top 3 recommended libraries
    4. For each library, visit its official website or GitHub page
    5. Extract key information about each library:
       - Name
       - Brief description
       - Main features or advantages
       - GitHub stars (if available)
    
    Present your findings in a summary format comparing the three libraries.
    """

	# Create and run the agent
	agent = Agent(task=task, llm=llm)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
