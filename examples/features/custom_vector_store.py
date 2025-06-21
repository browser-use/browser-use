"""
Script that demonstrates how to use the new customizable MemoryConfig with Browser Use, showcasing two different vector store providers:
the default FAISS (local) and a more scalable option like Qdrant
You'll need a Qdrant server running locally to run the Qdrant example.
You can visualize your Qdrant memories at http://localhost:6333/dashboard#/collections
"""

import asyncio
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from browser_use import Agent
from browser_use.agent.memory import MemoryConfig

# Load environment variables (e.g., OPENAI_API_KEY)
load_dotenv()

# Ensure OpenAI API key is set
if not os.getenv('OPENAI_API_KEY'):
	print('Error: OPENAI_API_KEY environment variable not set.')
	exit()


async def run_agent_with_memory_config(
	task: str,
	llm: ChatOpenAI,
	memory_config: MemoryConfig | None,
	agent_name: str,
	max_steps: int = 5,  # Keep low for demo purposes
):
	print(f'\n--- Running Agent: {agent_name} ---')
	if memory_config:
		print(f'Memory Provider: {memory_config.vector_store_provider}')
		if memory_config.vector_store_provider != 'memory':  # 'memory' provider doesn't use path or collection
			print(f'Vector Store Collection: {memory_config.vector_store_config_dict["config"].get("collection_name", "N/A")}')
			if memory_config.vector_store_provider in ['faiss', 'chroma']:
				print(f'Vector Store Path: {memory_config.vector_store_config_dict["config"].get("path", "N/A")}')

	agent = Agent(
		task=task,
		llm=llm,
		enable_memory=True if memory_config else False,  # Enable memory if config is provided
		memory_config=memory_config,  # Pass the specific memory config
		# Set a lower planner_interval for more frequent planning in short demos
		# and potentially see memory summarization happen sooner if memory_interval is also low.
		planner_interval=2,
	)

	print(f'Starting task: {task}')
	history = await agent.run(max_steps=max_steps)

	print(f'\n--- {agent_name} Finished ---')
	print(f'Task completed: {history.is_done()}')
	print(f'Final result/summary: {history.final_result()}')
	print(f'Number of steps taken: {len(history.history)}')

	# Let's refine how to access summaries. The summary is added as a 'memory' type message.

	summaries_created = []
	for item in agent.message_manager.state.history.get_messages():
		# get_messages() returns tuples of (step_number, messages)
		if isinstance(item, tuple) and len(item) == 2:
			step_number, step_messages = item
			if isinstance(step_messages, list):
				for msg in step_messages:
					if (
						hasattr(msg, 'additional_kwargs')
						and msg.additional_kwargs.get('metadata', {}).get('message_type') == 'memory'
					):
						summaries_created.append(msg.content)
			elif (
				hasattr(step_messages, 'additional_kwargs')
				and step_messages.additional_kwargs.get('metadata', {}).get('message_type') == 'memory'
			):
				summaries_created.append(step_messages.content)

	if summaries_created:
		print('\nProcedural Summaries Created during run:')
		for i, summary in enumerate(summaries_created):
			print(f'  Summary {i + 1}: {summary[:150]}...')  # Print first 150 chars
	else:
		# Check if messages were consolidated by looking at the agent's final message history
		final_messages = agent.message_manager.get_messages()
		summaries_in_final_context = [
			m.content
			for m in final_messages
			if hasattr(m, 'additional_kwargs') and m.additional_kwargs.get('message_type') == 'memory'
		]
		if summaries_in_final_context:
			print('\nProcedural Summaries in final context:')
			for i, summary in enumerate(summaries_in_final_context):
				print(f'  Summary {i + 1}: {summary[:150]}...')
		else:
			print(
				'No explicit procedural summaries found in final context (task might have been too short or memory interval not reached).'
			)

	print('---------------------------\n')
	return history


async def main():
	"""Main function to run the agent with different memory configurations."""
	common_task = 'Find the current CEO of OpenAI and then search for news about their latest projects. Summarize your findings.'
	shared_agent_id = 'persistent_browser_agent_001'  # Use the same ID to test persistence with Qdrant

	# Initialize the LLM (e.g., OpenAI's GPT-4o)
	# Ensure your OPENAI_API_KEY is set in your environment or .env file
	llm = ChatOpenAI(model='gpt-4o', temperature=0)

	# --- Scenario 1: Default FAISS Memory ---
	# MemoryConfig will use its defaults: FAISS, HuggingFace embedder if llm_instance not directly used by Mem0 for defaults
	# Since we pass llm_instance, it will likely pick OpenAI embedder
	faiss_memory_config = MemoryConfig(
		llm_instance=llm,  # Crucial for Mem0 to use this LLM for summarization
		agent_id=shared_agent_id,
		memory_interval=3,  # Summarize more frequently for demo
		# vector_store_provider is 'faiss' by default
		# embedder_provider will default based on llm_instance
	)
	await run_agent_with_memory_config(common_task, llm, faiss_memory_config, 'Agent with FAISS Memory')

	print('\n === PAUSE: Check FAISS data in /tmp/mem0... (if created) ===\n')
	# You might need to adjust the path based on your embedder_dims, e.g., /tmp/mem0_1536_faiss
	input('Press Enter to continue to Qdrant example...')

	# --- Scenario 2: Qdrant Memory ---
	# Ensure Qdrant server is running (e.g., `docker run -p 6333:6333 qdrant/qdrant`)
	print('Attempting to use Qdrant. Make sure Qdrant server is running on localhost:6333.')
	try:
		qdrant_memory_config = MemoryConfig(
			llm_instance=llm,  # Pass the LLM for Mem0's internal use
			agent_id=shared_agent_id,  # Same agent_id for potential persistence
			memory_interval=3,  # Summarize more frequently
			embedder_provider='openai',  # Explicitly set for consistency
			embedder_model='text-embedding-3-small',
			embedder_dims=1536,
			vector_store_provider='qdrant',
			vector_store_collection_name='browser_use_qdrant_demo',  # Custom collection name
			vector_store_config_override={
				'host': 'localhost',
				'port': 6333,
				# For Qdrant Cloud, you'd add "api_key": "YOUR_QDRANT_CLOUD_KEY", "url": "YOUR_QDRANT_CLOUD_URL"
				# "path": ":memory:" # For in-memory Qdrant, useful for quick tests without persistence
			},
		)
		await run_agent_with_memory_config(
			common_task,  # Could be a follow-up task to test memory persistence
			llm,
			qdrant_memory_config,
			'Agent with Qdrant Memory',
		)
	except ImportError as e:
		print(f'Could not run Qdrant example due to missing dependency: {e}')
		print('Please install qdrant-client: pip install qdrant-client')
	except Exception as e:
		print(f'Error running Qdrant agent: {e}')
		print('Ensure Qdrant server is running and accessible.')

	# --- Scenario 3: No Memory (for comparison) ---
	# await run_agent_with_memory_config(
	#     common_task,
	#     llm,
	#     None, # Pass None for memory_config to disable memory
	#     "Agent with NO Memory"
	# )


if __name__ == '__main__':
	import sys

	if sys.platform.startswith('win'):
		# WindowsProactorEventLoopPolicy is only available on Windows
		try:
			asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore
		except AttributeError:
			pass  # Not on Windows, ignore
	asyncio.run(main())
