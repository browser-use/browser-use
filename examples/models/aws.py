"""
AWS Bedrock Examples

This file demonstrates how to use AWS Bedrock models with browser-use.
We provide two classes:
1. ChatAnthropicBedrock - Convenience class for Anthropic Claude models
2. ChatAWSBedrock - General AWS Bedrock client supporting all providers

Requirements:
- AWS credentials configured via environment variables
- boto3 installed: pip install boto3
- Access to AWS Bedrock models in your region
"""

import asyncio

from lmnr import Laminar

from browser_use import Agent
from browser_use.llm import ChatAnthropicBedrock, ChatAWSBedrock

Laminar.initialize()


async def example_anthropic_bedrock():
	"""Example using ChatAnthropicBedrock - convenience class for Claude models."""
	print('🔹 ChatAnthropicBedrock Example')

	# Initialize with Anthropic Claude via AWS Bedrock
	llm = ChatAnthropicBedrock(
		model='us.anthropic.claude-sonnet-4-20250514-v1:0',
		aws_region='us-east-1',
		temperature=0.7,
	)

	print(f'Model: {llm.name}')
	print(f'Provider: {llm.provider}')

	# Create agent
	agent = Agent(
		task="Navigate to google.com and search for 'AWS Bedrock pricing'",
		llm=llm,
	)

	print("Task: Navigate to google.com and search for 'AWS Bedrock pricing'")

	# Run the agent
	result = await agent.run(max_steps=2)
	print(f'Result: {result}')


async def example_aws_bedrock():
	"""Example using ChatAWSBedrock - general client for any Bedrock model."""
	print('\n🔹 ChatAWSBedrock Example')

	# Initialize with any AWS Bedrock model (using Meta Llama as example)
	llm = ChatAWSBedrock(
		model='us.meta.llama4-maverick-17b-instruct-v1:0',
		aws_region='us-east-1',
		temperature=0.5,
	)

	print(f'Model: {llm.name}')
	print(f'Provider: {llm.provider}')

	# Create agent
	agent = Agent(
		task='Go to github.com and find the most popular Python repository',
		llm=llm,
	)

	print('Task: Go to github.com and find the most popular Python repository')

	# Run the agent
	result = await agent.run(max_steps=2)
	print(f'Result: {result}')


async def main():
	"""Run AWS Bedrock examples."""
	print('🚀 AWS Bedrock Examples')
	print('=' * 40)

	print('Make sure you have AWS credentials configured:')
	print('export AWS_ACCESS_KEY_ID=your_key')
	print('export AWS_SECRET_ACCESS_KEY=your_secret')
	print('export AWS_DEFAULT_REGION=us-east-1')
	print('=' * 40)

	try:
		# Run both examples
		await example_aws_bedrock()
		await example_anthropic_bedrock()

	except Exception as e:
		print(f'❌ Error: {e}')
		print('Make sure you have:')
		print('- Valid AWS credentials configured')
		print('- Access to AWS Bedrock in your region')
		print('- boto3 installed: pip install boto3')


if __name__ == '__main__':
	asyncio.run(main())
