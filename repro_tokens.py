import asyncio
import json
from typing import Any

# Browser Use imports
from browser_use import Agent, Browser
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage


class MockTokenTrackerLLM:
	def __init__(self):
		self.model_name = 'mock-tracker'
		self.model = 'mock-tracker'
		self.provider = 'mock'

	async def ainvoke(self, messages: list[BaseMessage], output_format: Any = None, **kwargs: Any) -> ChatInvokeCompletion:
		# Calculate approximate tokens (char count / 4)
		total_chars = 0
		history_size = 0
		browser_state_size = 0
		read_state_size = 0

		print('\n[MockLLM] Input Message Stats:')
		print(f'  - Message Count: {len(messages)}')

		for m in messages:
			content = ''
			if isinstance(m.content, str):
				content = m.content
			elif isinstance(m.content, list):
				# Join text parts
				for part in m.content:
					if hasattr(part, 'text'):
						content += part.text + '\n'

			total_chars += len(content)

			# Inspect content for blocks
			if '<agent_history>' in content:
				start = content.find('<agent_history>')
				end = content.find('</agent_history>')
				size = end - start
				history_size += size
				print(f'  - History Block Size: {size} chars')
				# Sample history content
				sample = content[start : start + 200] + '...' if size > 200 else content[start:end]
				print(f'  - History Head: {sample.replace(chr(10), " ")}')

			if '<browser_state>' in content:
				start = content.find('<browser_state>')
				end = content.find('</browser_state>')
				size = end - start
				browser_state_size += size
				print(f'  - Browser State Size: {size} chars')

			if '<read_state>' in content:
				start = content.find('<read_state>')
				end = content.find('</read_state>')
				size = end - start
				read_state_size += size
				print(f'  - Read State Size: {size} chars')

		print(f'  - Total Chars: {total_chars}')
		print(f'  - Approx Tokens: {total_chars // 4}')

		# Create a dummy success response
		output_data = {
			'evaluation_previous_goal': 'Step completed',
			'memory': 'Performed action',
			'next_goal': 'Do next thing',
			'action': [{'done': {'text': 'done'}}],
		}

		# Convert to JSON string as the completion
		completion_text = json.dumps(output_data)

		return ChatInvokeCompletion(
			completion=completion_text,
			usage=ChatInvokeUsage(
				prompt_tokens=total_chars // 4,
				completion_tokens=10,
				total_tokens=(total_chars // 4) + 10,
				prompt_cached_tokens=0,
				prompt_cache_creation_tokens=0,
				prompt_image_tokens=0,
			),
			thinking='Mock thinking',
		)


async def main():
	# Setup browser
	browser = Browser()

	# Use our mock LLM
	llm = MockTokenTrackerLLM()

	# Run a task
	task = 'Go to google.com'

	agent = Agent(
		task=task,
		llm=llm,
		browser=browser,
	)

	print('--- Starting Agent Run ---')
	try:
		# We need to force at least 2 steps to see history growth
		# But Agent stops if action is 'done'.
		# We'll make the mock LLM return 'extract_content' first then 'done'.
		# Actually, let's just make it return 'scroll_down' once then 'done'.

		# Monkey patch the ainvoke to change behavior based on step?
		# A simple stateful LLM would be better.

		step_count = 0
		original_ainvoke = llm.ainvoke

		async def stateful_ainvoke(messages, output_format=None, **kwargs):
			nonlocal step_count
			step_count += 1
			print(f'\n--- STEP {step_count} ---')

			# Call original to log stats
			result = await original_ainvoke(messages, output_format, **kwargs)

			# Modify output based on step
			if step_count == 1:
				# Step 1: Extract content to test duplication
				action = {'extract_content': {'goal': 'test content'}}
				data = {
					'evaluation_previous_goal': 'Started',
					'memory': 'Started task',
					'next_goal': 'Extract data',
					'action': [action],
				}
			elif step_count == 2:
				# Step 2: See if extracted content is duplicated in history & read_state
				action = {'scroll_down': {'amount': 100}}
				data = {
					'evaluation_previous_goal': 'Extracted',
					'memory': 'Extracted content',
					'next_goal': 'Scroll',
					'action': [action],
				}
			else:
				action = {'done': {'text': 'finished'}}
				data = {'evaluation_previous_goal': 'Scrolled', 'memory': 'Done', 'next_goal': 'Finish', 'action': [action]}

			result.completion = json.dumps(data)
			return result

		llm.ainvoke = stateful_ainvoke

		history = await agent.run(max_steps=4)

	except Exception as e:
		print(f'Error: {e}')
		import traceback

		traceback.print_exc()

	await browser.close()


if __name__ == '__main__':
	asyncio.run(main())
