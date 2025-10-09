"""
Simple test for token cost tracking with real LLM calls.

Tests ChatOpenAI and ChatGoogle by iteratively generating countries.
"""

import asyncio
import logging

from browser_use.llm import ChatGoogle, ChatOpenAI
from browser_use.llm.messages import AssistantMessage, SystemMessage, UserMessage
from browser_use.tokens.service import TokenCost

# Optional OCI import
try:
	from examples.models.oci_models import meta_llm

	OCI_MODELS_AVAILABLE = True
except ImportError:
	meta_llm = None
	OCI_MODELS_AVAILABLE = False


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def get_oci_model_if_available():
	"""Create OCI model for testing if credentials are available."""
	if not OCI_MODELS_AVAILABLE:
		return None

	# Try to create OCI model with mock/test configuration
	# These values should be replaced with real ones if testing with actual OCI
	try:
		# get any of the llm xai_llm or cohere_llm
		return meta_llm

	except Exception as e:
		logger.info(f'OCI model not available for testing: {e}')
		return None


async def test_iterative_country_generation():
	"""Test token cost tracking with iterative country generation"""

	# Initialize token cost service
	tc = TokenCost(include_cost=True)

	# System prompt that explains the iterative task
	system_prompt = """You are a country name generator. When asked, you will provide exactly ONE country name and nothing else.
Each time you're asked to continue, provide the next country name that hasn't been mentioned yet.
Keep track of which countries you've already said and don't repeat them.
Only output the country name, no numbers, no punctuation, just the name."""

	# Test with different models
	models = []
	models.append(ChatOpenAI(model='gpt-4.1'))  # Commented out - requires OPENAI_API_KEY
	models.append(ChatGoogle(model='gemini-2.0-flash-exp'))

	# Add OCI model if available
	oci_model = get_oci_model_if_available()
	if oci_model:
		models.append(oci_model)
		print(f'✅ OCI model added to test: {oci_model.name}')
	else:
		print('ℹ️  OCI model not available (install with pip install browser-use[oci] and configure credentials)')

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

	summary = await tc.get_usage_summary()
	print(f'Total calls: {summary.entry_count}')
	print(f'Total tokens: {summary.total_tokens:,}')
	print(f'Total cost: ${summary.total_cost:.6f}')

	expected_cost = 0
	expected_invocations = 0

	print('\n📊 Cost breakdown by model:')
	for model, stats in summary.by_model.items():
		expected_cost += stats.cost
		expected_invocations += stats.invocations

		print(f'\n{model}:')
		print(f'  Calls: {stats.invocations}')
		print(f'  Prompt tokens: {stats.prompt_tokens:,}')
		print(f'  Completion tokens: {stats.completion_tokens:,}')
		print(f'  Total tokens: {stats.total_tokens:,}')
		print(f'  Cost: ${stats.cost:.6f}')
		print(f'  Average tokens per call: {stats.average_tokens_per_invocation:.1f}')

	assert summary.entry_count == expected_invocations, f'Expected {expected_invocations} invocations, got {summary.entry_count}'
	assert abs(summary.total_cost - expected_cost) < 1e-6, (
		f'Expected total cost ${expected_cost:.6f}, got ${summary.total_cost:.6f}'
	)


if __name__ == '__main__':
	# Run the test
	asyncio.run(test_iterative_country_generation())
