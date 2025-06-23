"""
Simple test for token cost tracking with real LLM calls.

Tests ChatOpenAI and ChatGoogle by iteratively generating countries.
"""

import asyncio
import logging

from browser_use.llm import ChatOpenAI
from browser_use.llm.messages import AssistantMessage, SystemMessage, UserMessage
from browser_use.tokens.service import TokenCost

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


async def test_iterative_country_generation():
	"""Test token cost tracking with iterative country generation"""

	# Initialize token cost service
	tc = TokenCost()

	# System prompt that explains the iterative task
	system_prompt = """You are a country name generator. When asked, you will provide exactly ONE country name and nothing else.
Each time you're asked to continue, provide the next country name that hasn't been mentioned yet.
Keep track of which countries you've already said and don't repeat them.
Only output the country name, no numbers, no punctuation, just the name."""

	# Test with different models
	models = [
		ChatOpenAI(model='gpt-4.1'),
		# ChatGoogle(model='gemini-2.0-flash-exp'),
	]

	print('\n🌍 Iterative Country Generation Test')
	print('=' * 80)

	for llm in models:
		print(f'\n📍 Testing {llm.model}')
		print('-' * 60)

		# Register the LLM for automatic tracking
		tc.register_llm(llm)

		# Initialize conversation
		messages = [SystemMessage(content=system_prompt), UserMessage(content='Give me a country name')]

		countries = []

		# Generate 10 countries iteratively
		for i in range(10):
			# Call the LLM
			result = await llm.ainvoke(messages)
			country = result.completion.strip()
			countries.append(country)

			# Add the response to messages
			messages.append(AssistantMessage(content=country))

			# Add the next request (except for the last iteration)
			if i < 9:
				messages.append(UserMessage(content='Next country please'))

			print(f'  Country {i + 1}: {country}')

		print(f'\n  Generated countries: {", ".join(countries)}')

	# Display cost summary
	print('\n💰 Cost Summary')
	print('=' * 80)

	summary = tc.get_usage_summary()
	print(f'Total calls: {summary.entry_count}')
	print(f'Total tokens: {summary.total_tokens:,}')
	print(f'Total cost: ${summary.total_cost:.6f}')

	print('\n📊 Cost breakdown by model:')
	for model, stats in summary.by_model.items():
		print(f'\n{model}:')
		print(f'  Calls: {stats.invocations}')
		print(f'  Prompt tokens: {stats.prompt_tokens:,}')
		print(f'  Completion tokens: {stats.completion_tokens:,}')
		print(f'  Total tokens: {stats.total_tokens:,}')
		print(f'  Cost: ${stats.cost:.6f}')
		print(f'  Average tokens per call: {stats.average_tokens_per_invocation:.1f}')


if __name__ == '__main__':
	# Run the test
	asyncio.run(test_iterative_country_generation())
