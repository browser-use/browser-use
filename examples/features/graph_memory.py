"""
This example demonstrates how to use Browser Use's Mem0 graph memory with Neo4j.
You must have a running Neo4j instance and the necessary environment variables set.
"""

import asyncio
import os
from dotenv import load_dotenv

from browser_use import Agent
from browser_use.agent.memory import MemoryConfig
from langchain_openai import ChatOpenAI

load_dotenv()
NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

print(f'Attempting direct connect to URI: {NEO4J_URI}, User: {NEO4J_USERNAME}')

# --- 1. Initialize LLMs ---
agent_llm = ChatOpenAI(model='gpt-4o-mini', temperature=0.0, api_key=OPENAI_API_KEY)

# --- 2. Configure Mem0 Graph Memory via Browser Use's MemoryConfig ---
# Mem0 uses agent_id as user_id for graph operations context.
AGENT_ID_FOR_MEM0 = 'user_browser_task_graph_v1'

graph_memory_config = MemoryConfig(
	# Main LLM instance for Mem0
	llm_instance=agent_llm,
	agent_id=AGENT_ID_FOR_MEM0,
	memory_interval=2,
	# --- Graph Store Configuration ---
	graph_store_provider='neo4j',
	graph_store_config_override={
		'url': NEO4J_URI,
		'username': NEO4J_USERNAME,
		'password': NEO4J_PASSWORD,
	},
	# Optional: Override LLM specifically for graph operations within Mem0.
	# This tells Mem0 to use `mem0_internal_graph_llm` for its graph-related LLM calls.
	graph_store_llm_config_override={
		'provider': 'openai',
		'config': {'model': 'gpt-4o-mini', 'api_key': OPENAI_API_KEY, 'temperature': 0.0},
	},
	# Optional: Custom prompt for Mem0's graph entity/relationship extraction.
	graph_store_custom_prompt=(
		'From the conversation and browser interactions, extract entities like URLs, search queries, '
		'page titles, section titles, key facts extracted, user intents, and agent actions. '
		"Use 'USER_ID' for the user ('user_browser_task_graph_v1' in this case) and 'AGENT' for the assistant. "
		'Capture relationships such as: '
		"'AGENT NAVIGATED_TO URL', 'AGENT SEARCHED_FOR Query', 'URL HAS_TITLE PageTitle', "
		"'PAGE_CONTENT_CONTAINS Fact', 'AGENT_EXTRACTED Fact FROM URL', "
		"'USER_ID TASKED_AGENT_WITH UserTask', 'AGENT_ACTION_PERFORMED ActionDetail'. "
		'Focus on the sequence of web operations and information flow.'
	),
)

TASK_DESCRIPTION = (
	'Go to en.wikipedia.org. Search for "Persistent Memory". '
	'Navigate to the "Persistent Memory" Wikipedia page. '
	'Find and remember the title of the first main section of content on that page. '
	'Then, state what you found.'
)

# --- 3. Initialize Browser Use Agent ---

agent = Agent(
	task=TASK_DESCRIPTION,
	llm=agent_llm,
	enable_memory=True,  # This is True by default if memory_config is provided
	memory_config=graph_memory_config,
)


async def main():
	print(f"Starting Browser Use Agent for task: '{TASK_DESCRIPTION}'")
	print(f'Mem0 is configured with Neo4j for graph memory. Agent ID: {AGENT_ID_FOR_MEM0}')
	print(f'Ensure Neo4j is running at: {NEO4J_URI}')

	try:
		history = await agent.run()
		print('\n--- Agent Run Completed ---')

		final_result = history.final_result()
		if final_result:
			print(f"Agent's final output: {final_result}")
		else:
			print('Agent did not produce a final output within max_steps.')

		print(f'\nTotal steps taken: {history.number_of_steps()}')
		print(f'Total duration: {history.total_duration_seconds():.2f}s')

		if history.has_errors():
			print('\nErrors occurred during the run:')
			for i, error_msg in enumerate(history.errors()):
				if error_msg:
					print(f'  Step {i + 1}: {error_msg}')
		else:
			print('\nNo errors reported during the run.')

	except Exception as e:
		print(f'An error occurred during agent execution: {e}')

	print('\n--- Verification ---')
	print(f"Check your Neo4j instance for graph data related to user_id '{AGENT_ID_FOR_MEM0}'.")
	print('Example Cypher query for Neo4j Browser:')
	print(
		f"MATCH (n)-[r]-(m) WHERE n.user_id = '{AGENT_ID_FOR_MEM0}' OR m.user_id = '{AGENT_ID_FOR_MEM0}' RETURN n, r, m LIMIT 50"
	)
	print("You should see nodes and relationships reflecting the agent's actions (navigation, search, extraction) and findings.")


if __name__ == '__main__':
	asyncio.run(main())
