"""
Inception Labs Integration with Browser-Use

This example demonstrates how to use Inception Labs diffusion models with browser-use.
Inception Labs offers OpenAI-compatible API with advanced diffusion models for reasoning.

@dev You need to add INCEPTION_API_KEY to your environment variables.
Get your API key from: https://api.inceptionlabs.ai/

Key points:
- Uses ChatOpenAI with Inception Labs endpoint for full OpenAI compatibility
- Complete function calling support (unlike some other providers)
- Advanced diffusion model architecture optimized for reasoning
- Clean, reliable execution with structured outputs

Model used: mercury-coder
- Advanced diffusion model designed for coding and reasoning tasks
- Excellent performance on web automation and structured data extraction
- Full support for tool calling and JSON schema validation
"""

import asyncio
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from browser_use import Agent, BrowserSession

# Get API key from environment
inception_api_key = os.environ.get('INCEPTION_API_KEY')

# Create Inception Labs LLM using OpenAI compatibility
# This provides full OpenAI compatibility including structured outputs
llm = ChatOpenAI(
	model='mercury-coder',                      # Inception's diffusion model for reasoning
	base_url='https://api.inceptionlabs.ai/v1', # Inception Labs endpoint
	api_key=SecretStr(inception_api_key) if inception_api_key else None,
	temperature=0.3,
	max_tokens=1500,
)

# Define the task
task = """
Go to the Browser-Use GitHub repository and collect the following information:
1. Number of stars
2. Number of forks  
3. Number of open issues
4. Primary programming language
5. Latest release tag (if any)
6. Short description

Present the results in a structured format.
"""


async def main():
	start_time = time.time()
	
	# Create headless browser session with more robust settings
	browser_session = BrowserSession(
		headless=True,
		browser_config={
			'disable_web_security': True,
			'disable_features': ['VizDisplayCompositor'],
			'no_sandbox': True,
		}
	)
	
	agent = Agent(
		task=task,
		llm=llm,
		browser_session=browser_session,
		use_vision=False,  # Focus on reasoning capabilities
		tool_calling_method='raw',  # Force raw mode - ensures compatibility with OpenAI-like APIs
	)
	
	result = await agent.run(max_steps=15)
	
	end_time = time.time()
	execution_time = end_time - start_time
	
	print(f"Total execution time: {execution_time:.2f} seconds")


if __name__ == '__main__':
	asyncio.run(main()) 