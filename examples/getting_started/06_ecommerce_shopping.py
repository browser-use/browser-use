"""
Getting Started Example 6: E-commerce Shopping Simulation

This example demonstrates how to:
- Navigate an e-commerce website
- Search for products
- Add items to cart
- Compare prices and reviews
- Handle dynamic content loading

This builds on previous examples by simulating a real shopping experience.
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

	# Define an e-commerce shopping task
	task = """
    I want to shop for a laptop on an online store. Here's what I need you to do:
    
    1. Go to https://webscraper.io/test-sites/e-commerce/allinone
    2. Navigate to the "Computers" section, then "Laptops"
    3. Find the top 3 laptops by price (highest to lowest)
    4. For each laptop, extract:
       - Name and brand
       - Price
       - Available ratings/reviews if any
       - Key specifications if visible
    5. Add the most expensive laptop to the cart
    6. Proceed to the cart and verify the item was added correctly
    
    Present your findings as a shopping report with product comparisons and your cart summary.
    """

	# Create and run the agent
	agent = Agent(task=task, llm=llm)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())