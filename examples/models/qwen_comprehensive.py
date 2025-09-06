"""
Comprehensive example demonstrating Qwen integration with browser-use.

This example shows:
1. Basic usage with different models
2. Structured output
3. Different base URLs (International vs China)
4. Parameter customization
"""

import asyncio
import os

from pydantic import BaseModel

from browser_use import Agent
from browser_use.llm import ChatQwen


class SearchResult(BaseModel):
	"""Structured output model for search results."""

	query: str
	summary: str
	found_results: bool


async def basic_qwen_usage():
	"""Basic usage example with Qwen."""
	qwen_api_key = os.getenv('QWEN_API_KEY')
	if not qwen_api_key:
		print('Please set QWEN_API_KEY environment variable')
		print('Get your API key from: https://bailian.console.aliyun.com/')
		return

	# Basic configuration
	llm = ChatQwen(
		model='qwen-plus',
		api_key=qwen_api_key,
		base_url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
		temperature=0.1,
		max_tokens=1000,
	)

	agent = Agent(
		task='Search for recent developments in quantum computing',
		llm=llm,
		use_vision=True,
	)

	result = await agent.run()
	print(f'Basic task result: {result}')


async def qwen_with_different_models():
	"""Example using different Qwen model variants."""
	qwen_api_key = os.getenv('QWEN_API_KEY')
	if not qwen_api_key:
		return

	models_to_try = ['qwen-plus', 'qwen-turbo']

	for model in models_to_try:
		print(f'\\nTrying model: {model}')
		try:
			llm = ChatQwen(
				model=model,
				api_key=qwen_api_key,
				base_url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
				temperature=0,
				max_tokens=500,
			)

			agent = Agent(
				task='Find information about the latest AI news, search briefly',
				llm=llm,
				use_vision=False,
			)

			result = await agent.run()
			print(f'{model} completed successfully')

		except Exception as e:
			print(f'{model} failed: {e}')


async def qwen_with_structured_output():
	"""Example using Qwen with structured output."""
	qwen_api_key = os.getenv('QWEN_API_KEY')
	if not qwen_api_key:
		return

	llm = ChatQwen(
		model='qwen-plus',
		api_key=qwen_api_key,
		base_url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
		temperature=0,
	)

	agent = Agent(
		task='Search for information about Python programming and summarize findings',
		llm=llm,
		use_vision=False,
	)

	# This would work with the agent's structured output capabilities
	result = await agent.run()
	print(f'Structured output result: {result}')


async def qwen_international_vs_china():
	"""Example showing different base URLs for international vs China regions."""
	qwen_api_key = os.getenv('QWEN_API_KEY')
	if not qwen_api_key:
		return

	# International endpoint
	llm_intl = ChatQwen(
		model='qwen-plus',
		api_key=qwen_api_key,
		base_url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
		temperature=0.1,
	)

	# China endpoint (if you're in mainland China)
	llm_china = ChatQwen(
		model='qwen-plus',
		api_key=qwen_api_key,
		base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
		temperature=0.1,
	)

	print('Using international endpoint...')
	agent_intl = Agent(
		task='Quick search: What is machine learning?',
		llm=llm_intl,
		use_vision=False,
	)

	try:
		result = await agent_intl.run()
		print('International endpoint successful')
	except Exception as e:
		print(f'International endpoint failed: {e}')


async def qwen_with_custom_parameters():
	"""Example showing customization of Qwen parameters."""
	qwen_api_key = os.getenv('QWEN_API_KEY')
	if not qwen_api_key:
		return

	# Highly creative configuration
	llm_creative = ChatQwen(
		model='qwen-plus',
		api_key=qwen_api_key,
		base_url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
		temperature=0.9,
		top_p=0.95,
		max_tokens=1500,
		seed=42,  # For reproducible results
	)

	# Conservative configuration
	llm_conservative = ChatQwen(
		model='qwen-plus',
		api_key=qwen_api_key,
		base_url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
		temperature=0.1,
		top_p=0.1,
		max_tokens=500,
	)

	print('Creative configuration...')
	agent_creative = Agent(
		task='Search for creative AI applications in art and music',
		llm=llm_creative,
		use_vision=False,
	)

	print('Conservative configuration...')
	agent_conservative = Agent(
		task='Search for factual information about renewable energy',
		llm=llm_conservative,
		use_vision=False,
	)

	# Run both agents
	try:
		result1 = await agent_creative.run()
		print('Creative agent completed')

		result2 = await agent_conservative.run()
		print('Conservative agent completed')

	except Exception as e:
		print(f'Agent execution failed: {e}')


async def main():
	"""Run all examples."""
	print('Running Qwen comprehensive examples...')

	await basic_qwen_usage()
	print('\\n' + '=' * 50 + '\\n')

	await qwen_with_different_models()
	print('\\n' + '=' * 50 + '\\n')

	await qwen_with_structured_output()
	print('\\n' + '=' * 50 + '\\n')

	await qwen_international_vs_china()
	print('\\n' + '=' * 50 + '\\n')

	await qwen_with_custom_parameters()
	print('\\nAll examples completed!')


if __name__ == '__main__':
	asyncio.run(main())
