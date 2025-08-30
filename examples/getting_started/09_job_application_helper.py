"""
Getting Started Example 9: Job Application Helper

This example demonstrates how to:
- Navigate job boards and career sites
- Search for specific job opportunities
- Extract job requirements and details
- Fill out application forms
- Automate repetitive job search tasks

This shows how to streamline job searching and application processes.
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

	# Define a job search automation task
	task = """
    Help me search for Python developer jobs. Here's what I need:
    
    1. Go to https://stackoverflow.com/jobs (or if redirected, use the current jobs section)
    2. Search for "Python developer" or "Python engineer" positions
    3. Filter for remote or hybrid positions if possible
    4. Extract details from the top 5 job listings:
       - Job title and company name
       - Location/remote status
       - Salary range (if listed)
       - Required experience level
       - Key skills and technologies mentioned
       - Job posting date
    
    5. Click on the most relevant job (based on remote work and good salary)
    6. Extract the full job description and requirements
    7. Identify any application process information
    
    Present this as a job search report with:
    - Summary of the job market for Python developers
    - Detailed analysis of the top opportunity
    - Key skills that appear most frequently
    - Salary ranges and trends
    - Application strategy recommendations
    """

	# Create and run the agent
	agent = Agent(task=task, llm=llm)
	await agent.run()


if __name__ == '__main__':
	asyncio.run(main())