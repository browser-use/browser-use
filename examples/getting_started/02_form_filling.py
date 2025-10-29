"""
Getting Started Example 2: Form Filling

This example demonstrates how to:
- Navigate to a website with forms
- Fill out input fields
- Submit forms
- Handle basic form interactions

This builds on the basic search example by showing more complex interactions.

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

from browser_use import Agent, ChatGoogle


api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')
from browser_use import Agent, ChatBrowserUse


async def main():
	# Initialize the model
	llm = ChatGoogle(model='gemini-flash-latest', api_key=api_key)
	llm = ChatBrowserUse()

	# Define a form filling task
	task = """
    Go to https://docs.google.com/forms/d/e/1FAIpQLSfWo0CRmSQWpxycz19rCe0bf_hfgAryOInpsjyXlppf4vbWqA/viewform?usp=sharing&ouid=105950265099190792401 and fill out the contact form with:
    - Customer name: John Doe
    - Telephone: 555-123-4567
    - Email: john.doe@example.com
    - Organization : Example Corp
    - no of days attending: 3
    - dietary requirements: Vegetarian
    
    
    Then submit the form and tell me what response you get.
    """

	# Create and run the agent
	agent = Agent(task=task, llm=llm)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())
