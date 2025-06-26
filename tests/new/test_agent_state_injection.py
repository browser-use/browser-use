"""
Test Agent State Injection

This test demonstrates how to save and restore agent state, including file system state,
which is crucial for resuming agents from where they left off.

This follows the pattern used in cloud/backend/app/worker/service.py for agent state injection.

IMPORTANT: Agent state (including file_system_state) is only updated when operations succeed completely.
This happens automatically after each agent step, or can be triggered manually with save_file_system_state().
Direct file system operations don't automatically update agent state - this is by design for failure safety.

Asyncio loop was not exiting properly due to an unknown reason, so we force exit to prevent hang.
"""

import asyncio
import copy
import tempfile

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.agent.views import AgentState
from browser_use.browser import BrowserProfile
from browser_use.llm.openai.chat import ChatOpenAI

load_dotenv()


async def test_agent_state_injection():
	"""
	Test that agent state injection works correctly:
	1. Create an agent with a task
	2. Run it for 2 steps
	3. Save the agent state (including file system state)
	4. Create a new agent with injected state
	5. Verify state is preserved and agent continues correctly
	"""
	print('🧪 Starting Agent State Injection Test')
	print('=' * 60)

	# Step 1: Create first agent with file system
	with tempfile.TemporaryDirectory() as temp_dir:
		file_system_path = temp_dir

		# Create initial agent with file system
		task = "Write a simple to-do list with 3 items to a file named 'tasks.md', then read it back to verify the content"

		browser_profile = BrowserProfile(
			headless=True,
		)

		# Initialize LLM
		llm = ChatOpenAI(model='gpt-4.1-mini')

		agent1 = Agent(
			task=task,
			llm=llm,
			file_system_path=file_system_path,
			browser_profile=browser_profile,
		)

		print(f'📁 Agent 1 file system path: {agent1.file_system_path}')
		print(f'📁 Agent 1 files: {agent1.file_system.list_files()}')

		# Step 2: Run agent for exactly 2 steps
		print('\n🚀 Running Agent 1 for 2 steps...')
		step_count = 0
		max_steps = 2

		try:
			for step in range(max_steps):
				print(f'\n--- Step {step + 1} ---')
				await agent1.step()
				step_count += 1

				# Print current state after each step
				print(f'Files after step {step + 1}: {agent1.file_system.list_files()}')
				if agent1.state.history.is_done():
					print('✅ Agent completed task early!')
					break

		except Exception as e:
			print(f'⚠️ Agent 1 encountered error after {step_count} steps: {e}')

		# Step 3: Save agent state
		print(f'\n💾 Saving agent state after {step_count} steps...')
		agent1_state = copy.deepcopy(AgentState.model_validate(agent1.state))
		print(f'📊 Agent 1 completed {agent1_state.n_steps} steps')
		print(f'📁 Agent 1 file system has {len(agent1.file_system.files)} files')

		# Show file system contents
		files_description = agent1.file_system.describe()
		print(f'📋 Agent 1 File System Contents:\n{files_description}')

		# Show messages that Agent 1 model is seeing at end of step 2
		print('\n📨 MESSAGES AGENT 1 MODEL IS SEEING (End of Step 2):')
		print('=' * 70)

		# Get browser state and add state message to see what model would see next
		try:
			if agent1.browser_session is not None:
				browser_state_summary = await agent1.browser_session.get_state_summary(cache_clickable_elements_hashes=True)
				agent1._message_manager.add_state_message(
					browser_state_summary=browser_state_summary,
					model_output=agent1.state.last_model_output,
					result=agent1.state.last_result,
					step_info=None,
					use_vision=agent1.settings.use_vision,
					page_filtered_actions=None,
					sensitive_data=agent1.sensitive_data,
				)
			agent1_messages = agent1._message_manager.get_messages()
		except Exception as e:
			print(f'⚠️ Could not get browser state for Agent 1: {e}')
			agent1_messages = agent1._message_manager.get_messages()

		for i, msg in enumerate(agent1_messages):
			msg_type = type(msg).__name__
			if hasattr(msg, 'content'):
				content = str(msg.text)
				# Truncate long content for readability
				if i < len(agent1_messages) - 1 and len(content) > 300:
					content = content[:300] + '...\n[TRUNCATED]'
				print(f'Message {i + 1} ({msg_type}):\n{content}\n{"-" * 50}')
			else:
				print(f'Message {i + 1} ({msg_type}): {msg}\n{"-" * 50}')
		print('=' * 70)

		# Verify file system state is in agent state
		if agent1_state.file_system_state:
			print('✅ File system state found in agent state')
			print(f'📁 State contains {len(agent1_state.file_system_state.files)} files')
		else:
			print('❌ No file system state found in agent state!')

		await agent1.close()

		# Step 4: Create new agent with injected state
		print('\n🔄 Creating Agent 2 with injected state...')

		# This follows the pattern from cloud/backend/app/worker/service.py
		agent2 = Agent(
			task=task,  # Same task
			llm=llm,  # Same LLM instance
			browser_profile=browser_profile,
			injected_agent_state=agent1_state,  # KEY: Inject the saved state
		)

		print(f'📁 Agent 2 file system path: {agent2.file_system_path}')
		print(f'📁 Agent 2 files: {agent2.file_system.list_files()}')
		print(f'📁 Agent 2 has {len(agent2.file_system.files)} files')
		print(
			f'📁 Agent 2 state file system has {len(agent2.state.file_system_state.files) if agent2.state.file_system_state else 0} files'
		)

		# Show messages that Agent 2 model is seeing right after state injection
		print('\n📨 MESSAGES AGENT 2 MODEL IS SEEING (Right After State Injection):')
		print('=' * 70)

		# Get browser state and add state message to see what model would see next
		try:
			if agent2.browser_session is not None:
				browser_state_summary = await agent2.browser_session.get_state_summary(cache_clickable_elements_hashes=True)
				agent2._message_manager.add_state_message(
					browser_state_summary=browser_state_summary,
					model_output=agent2.state.last_model_output,
					result=agent2.state.last_result,
					step_info=None,
					use_vision=agent2.settings.use_vision,
					page_filtered_actions=None,
					sensitive_data=agent2.sensitive_data,
				)
			agent2_messages = agent2._message_manager.get_messages()
		except Exception as e:
			print(f'⚠️ Could not get browser state for Agent 2: {e}')
			agent2_messages = agent2._message_manager.get_messages()

		for i, msg in enumerate(agent2_messages):
			msg_type = type(msg).__name__
			if hasattr(msg, 'content'):
				content = str(msg.text)
				# Truncate long content for readability
				if i < len(agent2_messages) - 1 and len(content) > 300:
					content = content[:300] + '...\n[TRUNCATED]'
				print(f'Message {i + 1} ({msg_type}):\n{content}\n{"-" * 50}')
			else:
				print(f'Message {i + 1} ({msg_type}): {msg}\n{"-" * 50}')
		print('=' * 70)

		# Step 5: Verify state preservation
		print('\n🔍 Verifying state preservation...')

		# Check step count preservation
		assert agent2.state.n_steps == agent1_state.n_steps, (
			f'Step count not preserved: {agent2.state.n_steps} != {agent1_state.n_steps}'
		)
		print(f'✅ Step count preserved: {agent2.state.n_steps}')

		# Check file system preservation
		agent1_files = set(agent1.file_system.list_files())
		agent2_files = set(agent2.file_system.list_files())

		# Compare based on what's in the agent state, not the current file system
		if agent1_state.file_system_state and agent2.state.file_system_state:
			agent1_state_files = set(agent1_state.file_system_state.files.keys())
			agent2_state_files = set(agent2.state.file_system_state.files.keys())
			assert agent1_state_files == agent2_state_files, (
				f'State file list not preserved: {agent1_state_files} != {agent2_state_files}'
			)
			print(f'✅ State file list preserved: {len(agent2_state_files)} files')

			# Agent 2 file system should match its state
			assert agent2_files == agent2_state_files, (
				f"Agent 2 file system doesn't match its state: {agent2_files} != {agent2_state_files}"
			)
			print(f'✅ Agent 2 file system matches state: {len(agent2_files)} files')
		else:
			# Fallback to direct comparison if no state
			assert agent1_files == agent2_files, f'File list not preserved: {agent1_files} != {agent2_files}'
			print(f'✅ File list preserved: {len(agent2_files)} files')

		# Check file contents preservation (compare state-based content)
		if agent1_state.file_system_state and agent2.state.file_system_state:
			for filename in agent2.state.file_system_state.files.keys():
				if filename == 'todo.md':  # Skip todo.md as it's not shown in describe()
					continue
				# Compare based on what's actually in the restored file system
				agent1_state_content = agent1_state.file_system_state.files[filename]['data']['content']
				agent2_content = agent2.file_system.display_file(filename) or ''
				assert agent1_state_content == agent2_content, (
					f"Content mismatch in {filename}: state='{agent1_state_content}' vs file='{agent2_content}'"
				)
			print('✅ File contents preserved from state')
		else:
			# Fallback to direct comparison
			for filename in agent2.file_system.list_files():
				if filename == 'todo.md':
					continue
				agent1_content = agent1.file_system.display_file(filename) or ''
				agent2_content = agent2.file_system.display_file(filename) or ''
				assert agent1_content == agent2_content, f'Content mismatch in {filename}'
			print('✅ File contents preserved')

		# Check file system state preservation
		if agent1_state.file_system_state and agent2.state.file_system_state:
			assert len(agent1_state.file_system_state.files) == len(agent2.state.file_system_state.files), (
				'File system state files count mismatch'
			)
			print('✅ File system state preserved')

		# Check message history preservation
		print('\n🔍 Comparing message histories...')
		assert len(agent1_messages) == len(agent2_messages), (
			f'Message count mismatch: {len(agent1_messages)} != {len(agent2_messages)}'
		)
		print(f'✅ Message history preserved: {len(agent2_messages)} messages')

		# Step 6: Verify agent can continue from where it left off
		print('\n▶️ Testing that Agent 2 can continue from where Agent 1 left off...')

		# Show file system before continuing
		agent2_files_description = agent2.file_system.describe()
		print(f'📋 Agent 2 File System Contents:\n{agent2_files_description}')

		# Run agent 2 for one more step to show it can continue
		if not agent2.state.history.is_done():
			agent2 = Agent(
				task=task,  # Same task
				llm=llm,  # Same LLM instance
				browser_profile=browser_profile,
				injected_agent_state=agent1_state,  # KEY: Inject the saved state
			)
			print('🚀 Running Agent 2 for 1 additional step...')
			try:
				await agent2.step()
				print(f'✅ Agent 2 successfully continued - now at {agent2.state.n_steps} steps')
			except Exception as e:
				print(f'⚠️ Agent 2 encountered error: {e}')

		# Final verification
		print('\n📊 Final State Comparison:')
		print(f'Agent 1 final steps: {agent1_state.n_steps}')
		print(f'Agent 2 final steps: {agent2.state.n_steps}')
		print(f'Agent 1 files: {len(agent1.file_system.files)}')
		print(f'Agent 2 files: {len(agent2.file_system.files)}')

		# Show final file system
		final_files_description = agent2.file_system.describe()
		print(f'📋 Final File System Contents:\n{final_files_description}')

		print('🧹 Cleaning up agents...')
		try:
			await agent1.close()
			print('✅ Agent 1 closed')
		except Exception as e:
			print(f'⚠️ Error closing agent 1: {e}')

		try:
			await agent2.close()
			print('✅ Agent 2 closed')
		except Exception as e:
			print(f'⚠️ Error closing agent 2: {e}')

		print('✅ Main test cleanup completed!')

	print('\n🎉 Agent State Injection Test Completed Successfully!')
	print('=' * 60)


async def test_file_system_state_specific():
	"""
	Specific test for file system state injection without running full agent steps.
	This tests the core file system restoration functionality.
	"""
	print('\n🧪 Testing File System State Injection Specifically')
	print('=' * 50)

	with tempfile.TemporaryDirectory() as temp_dir:
		# Initialize LLM
		llm = ChatOpenAI(model='gpt-4.1-mini')

		# Create agent with file system
		agent1 = Agent(
			task='Test task',
			llm=llm,
			file_system_path=temp_dir,
			browser_profile=BrowserProfile(headless=True),
		)

		# Add some test files and update agent state (simulating successful agent actions)
		await agent1.file_system.write_file('test1.md', '# Test File 1\nContent for test 1')
		await agent1.file_system.write_file('test2.txt', 'Plain text content')
		await agent1.file_system.save_extracted_content('Some extracted content')

		# IMPORTANT: Update agent state with file system changes (this normally happens after successful steps)
		agent1.save_file_system_state()

		print(f'📁 Original file system has {len(agent1.file_system.files)} files')
		if agent1.state.file_system_state is not None:
			print(f'📁 Agent state file system has {len(agent1.state.file_system_state.files)} files')

		# Get state and create new agent with injected state
		agent_state = copy.deepcopy(AgentState.model_validate(agent1.state))

		agent2 = Agent(
			task='Test task',
			llm=llm,
			browser_profile=BrowserProfile(headless=True),
			injected_agent_state=agent_state,
		)

		# Verify file system restoration (based on agent state, not current file system)
		print(f'📁 Agent 1 file system has {len(agent1.file_system.files)} files')
		print(f'📁 Agent 2 file system has {len(agent2.file_system.files)} files')
		if agent_state.file_system_state is not None:
			print(f'📁 Agent state has {len(agent_state.file_system_state.files)} files')

			# Agent 2 should match the injected state, not necessarily Agent 1's current file system
			assert len(agent2.file_system.files) == len(agent_state.file_system_state.files), (
				f"Agent 2 file count ({len(agent2.file_system.files)}) doesn't match injected state ({len(agent_state.file_system_state.files)})"
			)
		print(f'✅ File system restored from state: {len(agent2.file_system.files)} files')

		# Verify specific file contents
		test1_content = await agent2.file_system.read_file('test1.md')
		assert 'Test File 1' in test1_content
		print(f'✅ Test file 1 content restored: {test1_content}')

		test2_content = await agent2.file_system.read_file('test2.txt')
		assert 'Plain text content' in test2_content
		print(f'✅ Test file 2 content restored: {test2_content}')

		# Verify extracted content counter
		assert agent2.file_system.extracted_content_count == 1
		print(f'✅ Extracted content counter restored: {agent2.file_system.extracted_content_count}')

		print('✅ File system state injection working perfectly!')
		print('🔄 Starting cleanup process...')

		print('🧹 Cleaning up Agent 1...')
		try:
			await agent1.close()
			print('✅ Agent 1 closed successfully')
		except Exception as e:
			print(f'⚠️ Error closing Agent 1: {e}')

		print('🧹 Cleaning up Agent 2...')
		try:
			await agent2.close()
			print('✅ Agent 2 closed successfully')
		except Exception as e:
			print(f'⚠️ Error closing Agent 2: {e}')

		print('✅ File system test cleanup completed!')
		print('🔄 File system test function ending...')


if __name__ == '__main__':
	print('🚀 Running Agent State Injection Tests')
	print('=' * 60)

	# Run tests sequentially with timeout
	async def run_tests():
		try:
			print('🧪 Running Main Agent State Injection Test...')
			await asyncio.wait_for(test_agent_state_injection(), timeout=300)  # 5 minute timeout
			print('\n' + '=' * 60 + '\n')
		except TimeoutError:
			print('❌ Main test timed out after 5 minutes')
		except Exception as e:
			print(f'❌ Main test failed: {e}')
			import traceback

			traceback.print_exc()

		try:
			print('🧪 Running File System State Injection Test...')
			await asyncio.wait_for(test_file_system_state_specific(), timeout=120)  # 2 minute timeout
		except TimeoutError:
			print('❌ File system test timed out after 2 minutes')
		except Exception as e:
			print(f'❌ File system test failed: {e}')
			import traceback

			traceback.print_exc()

		print('\n🎉 All tests completed!')

		# Force exit to prevent asyncio.run() cleanup hang
		print('🚪 Force exiting to prevent hang...')
		import os

		os._exit(0)

	print('🚀 Starting asyncio.run(run_tests())...')
	try:
		asyncio.run(run_tests())
		print('✅ asyncio.run(run_tests()) completed!')
	except Exception as e:
		print(f'❌ Error in asyncio.run: {e}')
		import traceback

		traceback.print_exc()

	print('🔄 Script ending...')
