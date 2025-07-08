import json
import os

import tiktoken

from browser_use.agent.views import AgentOutput
from browser_use.controller.service import Controller
from browser_use.llm.schema import SchemaOptimizer


def test_optimized_schema():
	"""Test the optimized schema generation and save to file."""

	# Create controller and get all registered actions
	controller = Controller()
	ActionModel = controller.registry.create_action_model()

	# Create the agent output model with custom actions
	agent_output_model = AgentOutput.type_with_custom_actions(ActionModel)

	# Get original schema for comparison
	original_schema = agent_output_model.model_json_schema()

	# Create the optimized schema
	optimized_schema = SchemaOptimizer.create_optimized_json_schema(agent_output_model)

	# Create tmp directory if it doesn't exist
	os.makedirs('./tmp', exist_ok=True)

	# Save optimized schema
	with open('./tmp/optimized_schema.json', 'w') as f:
		json.dump(optimized_schema, f, separators=(',', ':'), indent=2)

	print('✅ Optimized schema generated and saved to ./tmp/optimized_schema.json')

	# Compare token counts of both
	try:
		enc = tiktoken.encoding_for_model('gpt-4o')
	except KeyError:
		enc = tiktoken.get_encoding('cl100k_base')

	original_tokens = len(enc.encode(json.dumps(original_schema)))
	optimized_tokens = len(enc.encode(json.dumps(optimized_schema, separators=(',', ':'))))

	savings = original_tokens - optimized_tokens
	savings_percentage = (savings / original_tokens * 100) if original_tokens > 0 else 0

	print('\n📊 Token Count Comparison:')
	print(f'   Original schema: {original_tokens:,} tokens')
	print(f'   Optimized schema: {optimized_tokens:,} tokens')
	print(f'   Token savings: {savings:,} tokens ({savings_percentage:.1f}% reduction)')

	# Count tokens per action in optimized schema
	print('\n🔍 Tokens per Action in Optimized Schema:')

	if 'properties' in optimized_schema and 'action' in optimized_schema['properties']:
		action_prop = optimized_schema['properties']['action']
		if 'items' in action_prop and 'anyOf' in action_prop['items']:
			actions = action_prop['items']['anyOf']

			total_action_tokens = 0
			for i, action in enumerate(actions):
				action_json = json.dumps(action, separators=(',', ':'))
				action_tokens = len(enc.encode(action_json))
				total_action_tokens += action_tokens

				# Try to get action name from the schema
				action_name = 'Unknown'
				if 'properties' in action:
					# Get the first property that's not common ones like 'index', 'reasoning'
					for prop_name in action['properties'].keys():
						if prop_name not in ['index', 'reasoning']:
							action_name = prop_name
							break

				print(f'   Action {i + 1} ({action_name}): {action_tokens:,} tokens')

			print('\n📈 Summary:')
			print(f'   Total actions: {len(actions)}')
			print(f'   Total action tokens: {total_action_tokens:,} tokens')
			print(f'   Average tokens per action: {total_action_tokens // len(actions):,} tokens')
			print(f'   Action tokens as % of total: {(total_action_tokens / optimized_tokens * 100):.1f}%')
		else:
			print('   No actions found in expected schema structure')
	else:
		print('   No action property found in optimized schema')


if __name__ == '__main__':
	test_optimized_schema()
