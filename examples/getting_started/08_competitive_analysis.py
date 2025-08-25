"""
Getting Started Example 8: Competitive Analysis

This example demonstrates how to:
- Visit multiple competitor websites
- Extract business information
- Compare features and pricing
- Analyze market positioning
- Generate competitive intelligence reports

This shows how to automate competitive research using browser automation.
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

	# Define a competitive analysis task
	task = """
    I need to analyze web scraping tool competitors. Please research these three companies:
    
    1. First, visit https://scrapfly.io/
       - Find their pricing plans
       - Identify key features
       - Look for any free tier or trial information
       - Note their main value propositions
    
    2. Then visit https://apify.com/
       - Extract similar information about pricing and features
       - Look at their marketplace/actor store
       - Identify their target market focus
    
    3. Finally, visit https://scraperapi.com/
       - Gather pricing and feature information
       - Look for their main differentiators
       - Check their documentation quality
    
    Create a competitive analysis report comparing:
    - Pricing models (per request, monthly, etc.)
    - Key features and capabilities
    - Target customer segments
    - Unique selling points
    - Market positioning
    
    Present this as a structured business intelligence report.
    """

	# Create and run the agent
	agent = Agent(task=task, llm=llm)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())