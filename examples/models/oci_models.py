"""
Oracle Cloud Infrastructure (OCI) Raw API Example

This example demonstrates how to use OCI's Generative AI service with browser-use
using the raw API integration (ChatOCIRaw) without Langchain dependencies.

@dev You need to:
1. Set up OCI configuration file at ~/.oci/config
2. Have access to OCI Generative AI models in your tenancy
3. Install the OCI Python SDK: uv add oci

Requirements:
- OCI account with Generative AI service access
- Proper OCI configuration and authentication
- Model deployment in your OCI compartment
"""

import asyncio
import os
import sys

from pydantic import BaseModel

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from browser_use import Agent
from browser_use.llm import ChatOCIRaw


class SearchSummary(BaseModel):
	query: str
	results_found: int
	top_result_title: str
	summary: str
	relevance_score: float


# Configuration examples for different providers
compartment_id = 'ocid1.tenancy.oc1..aaaaaaaayeiis5uk2nuubznrekd6xsm56k3m4i7tyvkxmr2ftojqfkpx2ura'
endpoint = 'https://inference.generativeai.us-chicago-1.oci.oraclecloud.com'

# Example 1: Meta Llama model (uses GenericChatRequest)
meta_model_id = 'ocid1.generativeaimodel.oc1.us-chicago-1.amaaaaaask7dceyarojgfh6msa452vziycwfymle5gxdvpwwxzara53topmq'


meta_llm = ChatOCIRaw(
	model_id=meta_model_id,
	service_endpoint=endpoint,
	compartment_id=compartment_id,
	provider='meta',  # Meta Llama model
	temperature=0.7,
	max_tokens=800,
	frequency_penalty=0.0,
	presence_penalty=0.0,
	top_p=0.9,
	auth_type='API_KEY',
	auth_profile='DEFAULT',
)
cohere_model_id = 'ocid1.generativeaimodel.oc1.us-chicago-1.amaaaaaask7dceyanrlpnq5ybfu5hnzarg7jomak3q6kyhkzjsl4qj24fyoq'

# Example 2: Cohere model (uses CohereChatRequest)
# cohere_model_id = "ocid1.generativeaimodel.oc1.us-chicago-1.amaaaaaask7dceyapnibwg42qjhwaxrlqfpreueirtwghiwvv2whsnwmnlva"
cohere_llm = ChatOCIRaw(
	model_id=cohere_model_id,
	service_endpoint=endpoint,
	compartment_id=compartment_id,
	provider='cohere',  # Cohere model
	temperature=1.0,
	max_tokens=600,
	frequency_penalty=0.0,
	top_p=0.75,
	top_k=0,  # Cohere-specific parameter
	auth_type='API_KEY',
	auth_profile='DEFAULT',
)

# Example 3: xAI model (uses GenericChatRequest)
xai_model_id = 'ocid1.generativeaimodel.oc1.us-chicago-1.amaaaaaask7dceya3bsfz4ogiuv3yc7gcnlry7gi3zzx6tnikg6jltqszm2q'
xai_llm = ChatOCIRaw(
	model_id=xai_model_id,
	service_endpoint=endpoint,
	compartment_id=compartment_id,
	provider='xai',  # xAI model
	temperature=1.0,
	max_tokens=20000,
	top_p=1.0,
	top_k=0,
	auth_type='API_KEY',
	auth_profile='DEFAULT',
)

# Use Meta model by default for this example
llm = xai_llm


async def basic_example():
	"""Basic example using ChatOCIRaw with a simple task."""
	print('🔹 Basic ChatOCIRaw Example')
	print('=' * 40)

	print(f'Model: {llm.name}')
	print(f'Provider: {llm.provider_name}')

	# Create agent with a simple task
	agent = Agent(
		task="Go to google.com and search for 'Oracle Cloud Infrastructure pricing'",
		llm=llm,
	)

	print("Task: Go to google.com and search for 'Oracle Cloud Infrastructure pricing'")

	# Run the agent
	try:
		result = await agent.run(max_steps=5)
		print('✅ Task completed successfully!')
		print(f'Final result: {result}')
	except Exception as e:
		print(f'❌ Error: {e}')


async def structured_output_example():
	"""Example demonstrating structured output with Pydantic models."""
	print('\n🔹 Structured Output Example')
	print('=' * 40)

	# Create agent that will return structured data
	agent = Agent(
		task="""Go to github.com, search for 'browser automation python', 
                find the most popular repository, and return structured information about it""",
		llm=llm,
		output_format=SearchSummary,  # This will enforce structured output
	)

	print('Task: Search GitHub for browser automation and return structured data')

	try:
		result = await agent.run(max_steps=5)

		if isinstance(result, SearchSummary):
			print('✅ Structured output received!')
			print(f'Query: {result.query}')
			print(f'Results Found: {result.results_found}')
			print(f'Top Result: {result.top_result_title}')
			print(f'Summary: {result.summary}')
			print(f'Relevance Score: {result.relevance_score}')
		else:
			print(f'Result: {result}')

	except Exception as e:
		print(f'❌ Error: {e}')


async def advanced_configuration_example():
	"""Example showing advanced configuration options."""
	print('\n🔹 Advanced Configuration Example')
	print('=' * 40)

	print(f'Model: {llm.name}')
	print(f'Provider: {llm.provider_name}')
	print('Configuration: Cohere model with instance principal auth')

	# Create agent with a more complex task
	agent = Agent(
		task="""Navigate to stackoverflow.com, search for questions about 'python web scraping' and tap search help, 
                analyze the top 3 questions, and provide a detailed summary of common challenges""",
		llm=llm,
	)

	print('Task: Analyze StackOverflow questions about Python web scraping')

	try:
		result = await agent.run(max_steps=8)
		print('✅ Advanced task completed!')
		print(f'Analysis result: {result}')
	except Exception as e:
		print(f'❌ Error: {e}')


async def provider_compatibility_test():
	"""Test different provider formats to verify compatibility."""
	print('\n🔹 Provider Compatibility Test')
	print('=' * 40)

	providers_to_test = [('Meta', meta_llm), ('Cohere', cohere_llm), ('xAI', xai_llm)]

	for provider_name, model in providers_to_test:
		print(f'\nTesting {provider_name} model...')
		print(f'Model ID: {model.model_id}')
		print(f'Provider: {model.provider}')
		print(f'Uses Cohere format: {model._uses_cohere_format()}')

		# Create a simple agent to test the model
		agent = Agent(
			task='Go to google.com and tell me what you see',
			llm=model,
		)

		try:
			result = await agent.run(max_steps=3)
			print(f'✅ {provider_name} model works correctly!')
			print(f'Result: {str(result)[:100]}...')
		except Exception as e:
			print(f'❌ {provider_name} model failed: {e}')


async def main():
	"""Run all OCI Raw examples."""
	print('🚀 Oracle Cloud Infrastructure (OCI) Raw API Examples')
	print('=' * 60)

	print('\n📋 Prerequisites:')
	print('1. OCI account with Generative AI service access')
	print('2. OCI configuration file at ~/.oci/config')
	print('3. Model deployed in your OCI compartment')
	print('4. Proper IAM permissions for Generative AI')
	print('5. OCI Python SDK installed: uv add oci')
	print('=' * 60)

	print('\n⚙️ Configuration Notes:')
	print('• Update model_id, service_endpoint, and compartment_id with your values')
	print('• Supported providers: "meta", "cohere", "xai"')
	print('• Auth types: "API_KEY", "INSTANCE_PRINCIPAL", "RESOURCE_PRINCIPAL"')
	print('• Default OCI config profile: "DEFAULT"')
	print('=' * 60)

	print('\n🔧 Provider-Specific API Formats:')
	print('• Meta/xAI models: Use GenericChatRequest with messages array')
	print('• Cohere models: Use CohereChatRequest with single message string')
	print('• The integration automatically detects and uses the correct format')
	print('=' * 60)

	try:
		# Run all examples
		await basic_example()
		await structured_output_example()
		await advanced_configuration_example()
		# await provider_compatibility_test()

		print('\n🎉 All examples completed successfully!')

	except Exception as e:
		print(f'\n❌ Example failed: {e}')
		print('\n🔧 Troubleshooting:')
		print('• Verify OCI configuration: oci setup config')
		print('• Check model OCID and availability')
		print('• Ensure compartment access and IAM permissions')
		print('• Verify service endpoint URL')
		print('• Check OCI Python SDK installation')
		print("• Ensure you're using the correct provider name in ChatOCIRaw")


if __name__ == '__main__':
	asyncio.run(main())
