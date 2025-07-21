import asyncio
import os

from base_agent import BaseAgent


async def main():
	"""Dynamic parallel orchestrator - input any prompt and get results."""

	# Get API key from environment variable only
	api_key = os.getenv('GOOGLE_API_KEY')
	if not api_key:
		print('Error: GOOGLE_API_KEY environment variable not set')
		print("Please set your Gemini API key: export GOOGLE_API_KEY='your_key_here'")
		return

	print(f'Using API key: {api_key[:10]}...')

	# Create base agent
	base_agent = BaseAgent(api_key=api_key, model='gemini-1.5-flash', max_workers=10, headless=False)

	await base_agent.initialize()

	# USER INPUT - Enter any prompt here
	print('\n' + '=' * 60)
	print('DYNAMIC PARALLEL ORCHESTRATOR')
	print('=' * 60)
	print('Enter any natural language task and the system will:')
	print('• Automatically analyze and decompose it')
	print('• Create the optimal number of workers (1-10)')
	print('• Execute tasks in parallel')
	print('• Return aggregated results')
	print('\n' + '-' * 60)

	# Get user input
	user_prompt = input('Enter your task: ').strip()

	if not user_prompt:
		print('No task entered. Exiting.')
		return

	print(f'\n🎯 Processing: {user_prompt}')
	print('=' * 60)

	try:
		# Process the task dynamically
		results = await base_agent.process_task(user_prompt)

		# Display results
		print('\n✅ RESULTS:')
		print('=' * 40)
		for key, result in results.items():
			print(f'\n{key}:')
			print(f'  {result}')

		# Save shared answers for Base Agent processing
		save_shared_answers_to_file(results, user_prompt)
		print('📄 Shared answers saved to: parallel_orchestrator/shared_answers.txt')
		print('📄 AI-cleaned final answer saved to: parallel_orchestrator/final_answers.txt')

	except Exception as e:
		print(f'❌ Error: {e}')

	# Cleanup
	await base_agent.cleanup()

	print('\n' + '=' * 60)
	print('TASK COMPLETED')
	print('=' * 60)


def save_shared_answers_to_file(results, original_prompt):
	"""Save raw shared answers for Base Agent AI processing."""
	filename = 'parallel_orchestrator/shared_answers.txt'

	with open(filename, 'w') as f:
		f.write('SHARED ANSWERS FOR BASE AGENT PROCESSING\n')
		f.write('=' * 50 + '\n\n')
		f.write(f'Original Task: {original_prompt}\n\n')
		f.write('Raw Results from Workers:\n')
		f.write('-' * 30 + '\n\n')

		for key, result in results.items():
			f.write(f'WORKER: {key}\n')
			f.write(f'RESULT: {result}\n')
			f.write('-' * 50 + '\n\n')


def save_clean_results_to_file(results, original_prompt):
	"""Save clean results to a simple file."""
	filename = 'parallel_orchestrator/final_answers.txt'

	with open(filename, 'w') as f:
		f.write('DYNAMIC PARALLEL ORCHESTRATOR RESULTS\n')
		f.write('=' * 40 + '\n\n')
		f.write(f'Original Task: {original_prompt}\n\n')
		f.write('Final Clean Answers:\n')
		f.write('-' * 20 + '\n\n')

		for key, result in results.items():
			# Extract the final clean answer
			if hasattr(result, 'all_results') and result.all_results:
				# Look for the final meaningful result
				final_answer = None
				for action_result in reversed(result.all_results):
					if hasattr(action_result, 'extracted_content') and action_result.extracted_content:
						content = action_result.extracted_content
						if content and len(content.strip()) > 10:  # Meaningful content
							final_answer = content
							break

				if final_answer:
					f.write(f'{key}: {final_answer}\n\n')
				else:
					f.write(f'{key}: No final result found\n\n')
			else:
				f.write(f'{key}: {result}\n\n')


if __name__ == '__main__':
	asyncio.run(main())
