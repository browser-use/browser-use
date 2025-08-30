"""
Getting Started Example 7: Social Media Monitoring

This example demonstrates how to:
- Navigate social media platforms
- Monitor trends and hashtags
- Extract social metrics
- Handle infinite scroll and dynamic loading
- Collect structured social data

This shows how to gather social intelligence using browser automation.
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

	# Define a social media monitoring task
	task = """
    I want to monitor what people are saying about "AI automation" on Hacker News. Here's what I need:
    
    1. Go to https://news.ycombinator.com/
    2. Search for posts containing "AI automation" or "browser automation"
    3. Find the top 5 most recent relevant posts
    4. For each post, extract:
       - Title and link
       - Number of points/upvotes
       - Number of comments
       - Author username
       - Posted time
    5. Click on the top 2 posts and read the first 3 top-level comments
    6. Summarize the general sentiment and key discussion points
    
    Present this as a social media monitoring report with trending topics and community sentiment.
    """

	# Create and run the agent
	agent = Agent(task=task, llm=llm)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())