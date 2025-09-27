"""
Simple test runner for agent tasks using OCI Raw API model.
Just runs the tasks from YAML files without complex judging.
"""

import asyncio
import glob
import logging
import os

import aiofiles
import yaml

from browser_use import Agent
from browser_use.logging_config import setup_logging
from examples.models.oci_models import meta_llm

# Enable debug logging
setup_logging(log_level=logging.INFO)


async def run_task_from_yaml(yaml_file):
	"""Load and run a single task from a YAML file"""
	print(f'\n🚀 Running task: {os.path.basename(yaml_file)}')
	print('=' * 50)

	# Load task from YAML
	async with aiofiles.open(yaml_file, 'r') as f:
		content = await f.read()
		task_data = yaml.safe_load(content)

	task_name = task_data.get('name', 'Unnamed Task')
	task_description = task_data['task']
	max_steps = task_data.get('max_steps', 15)

	print(f'Task Name: {task_name}')
	print(f'Description: {task_description}')
	print(f'Max Steps: {max_steps}')
	print('-' * 50)

	# Create OCI model
	model = meta_llm

	# Create and run agent
	agent = Agent(task=task_description, llm=model, use_vision=True)

	try:
		history = await agent.run(max_steps=max_steps)

		print('\n✅ Task completed!')
		print(f'Steps taken: {len(history.history) if hasattr(history, "history") else "Unknown"}')

		final_result = history.final_result()
		if final_result:
			print(f'Final result: {final_result}')
		else:
			print('No final result returned')

		return True

	except Exception as e:
		print(f'\n❌ Task failed with error: {str(e)}')
		return False


async def run_all_tasks():
	"""Find and run all YAML tasks in the current directory"""
	current_dir = os.path.dirname(__file__)
	yaml_files = glob.glob(os.path.join(current_dir, '*.yaml'))

	if not yaml_files:
		print('No YAML task files found in the current directory!')
		return

	print(f'Found {len(yaml_files)} task files:')
	for yaml_file in yaml_files:
		print(f'  - {os.path.basename(yaml_file)}')

	successful = 0
	total = len(yaml_files)

	for yaml_file in yaml_files:
		try:
			success = await run_task_from_yaml(yaml_file)
			if success:
				successful += 1
		except KeyboardInterrupt:
			print('\n🛑 Interrupted by user')
			break
		except Exception as e:
			print(f'❌ Failed to run {os.path.basename(yaml_file)}: {str(e)}')

	print(f'\n🏁 Summary: {successful}/{total} tasks completed successfully')


if __name__ == '__main__':
	import sys

	if len(sys.argv) > 1:
		# Run specific task file
		yaml_file = sys.argv[1]
		if not yaml_file.endswith('.yaml'):
			yaml_file += '.yaml'

		if not os.path.isabs(yaml_file):
			yaml_file = os.path.join(os.path.dirname(__file__), yaml_file)

		if os.path.exists(yaml_file):
			asyncio.run(run_task_from_yaml(yaml_file))
		else:
			print(f'Task file not found: {yaml_file}')
	else:
		# Run all tasks
		asyncio.run(run_all_tasks())
