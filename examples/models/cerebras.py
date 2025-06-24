"""
Cerebras Integration with Browser-Use

This example demonstrates how to use Cerebras models with browser-use through OpenAI compatibility.
Cerebras offers fast inference with their optimized hardware for large language models.

@dev You need to add CEREBRAS_API_KEY to your environment variables.
Get your API key from: https://cloud.cerebras.ai/

Key points:
- Uses ChatOpenAI with Cerebras endpoint for seamless compatibility
- No custom wrappers needed - just point to Cerebras API
- Supports all browser-use features including tool calling
- Fast inference thanks to Cerebras's specialized hardware

Model used: llama-4-scout-17b-16e-instruct
- High-performance model optimized for reasoning and tool use
- Excellent for web automation tasks
- Fast response times due to Cerebras hardware acceleration
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
cerebras_api_key = os.environ.get('CEREBRAS_API_KEY')

# Create Cerebras LLM using OpenAI compatibility
# This is the key insight - no custom wrappers needed!
llm = ChatOpenAI(
	model='llama-4-scout-17b-16e-instruct',  # Cerebras's high-performance model
	base_url='https://api.cerebras.ai/v1',   # Point to Cerebras endpoint
	api_key=SecretStr(cerebras_api_key) if cerebras_api_key else None,
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
		use_vision=False,  # Disabled for compatibility
		tool_calling_method='raw',  # Force raw mode - Cerebras doesn't support advanced JSON schemas
	)
	
	result = await agent.run(max_steps=15)
	
	end_time = time.time()
	execution_time = end_time - start_time
	
	print(f"Total execution time: {execution_time:.2f} seconds")


if __name__ == '__main__':
	asyncio.run(main()) 