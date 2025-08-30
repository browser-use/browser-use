"""
Getting Started Example 10: Content Creation Research

This example demonstrates how to:
- Research trending topics and keywords
- Analyze competitor content strategies
- Gather statistics and data points
- Find relevant sources and citations
- Automate content research workflows

This shows how to accelerate content creation through automated research.
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

	# Define a content research task
	task = """
    I want to create content about "the future of web automation". Help me research this topic:
    
    1. Start by searching Google for "web automation trends 2024" and "future of browser automation"
    2. Find 3 authoritative articles or blog posts on this topic
    3. For each article, extract:
       - Main predictions and trends mentioned
       - Key statistics or data points
       - Expert quotes or insights
       - Technical developments discussed
       - Publication date and source credibility
    
    4. Visit GitHub and search for trending repositories related to "browser automation" or "web scraping"
    5. Identify the top 3 most starred/active projects from the last year
    6. For each project, note:
       - Project name and description
       - Stars and recent activity
       - Key features or innovations
       - Programming language used
    
    7. Check one major tech news site (like TechCrunch, Wired, or Ars Technica) for recent articles about automation or AI
    
    Compile this into a content research brief with:
    - Current market trends and statistics
    - Expert opinions and predictions
    - Technical innovations and tools
    - Content angles and story ideas
    - Relevant sources and citations
    - Suggested headlines and topics
    """

	# Create and run the agent
	agent = Agent(task=task, llm=llm)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())