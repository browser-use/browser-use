"""
Test script to verify Gemini 3 native thinking and thought signatures work correctly.

Usage:
    GOOGLE_API_KEY=your_key uv run python test_gemini3_thinking.py

What to check:
    1. Native thinking is extracted from responses
    2. Thought signatures are captured and passed between turns
    3. AgentOutput.thinking is populated with native CoT
"""

import asyncio
import logging

from browser_use import Agent
from browser_use.browser import BrowserSession
from browser_use.llm.google.chat import ChatGoogle

# Enable debug logging to see thinking extraction
logging.basicConfig(
	level=logging.INFO,
	format='%(levelname)-8s [%(name)s] %(message)s',
)
# Set specific loggers to DEBUG for more detail
logging.getLogger('browser_use.llm.google').setLevel(logging.DEBUG)
logging.getLogger('browser_use.agent').setLevel(logging.DEBUG)


async def test_llm_directly():
	"""Test LLM directly to verify thinking extraction works."""
	print('\n' + '=' * 60)
	print('TEST 1: Direct LLM Call')
	print('=' * 60)

	from browser_use.llm.messages import UserMessage

	llm = ChatGoogle(
		model='gemini-3-flash-preview',
		thinking_level='low',
	)

	print(f'Model: {llm.model}')
	print(f'is_gemini_3: {llm.is_gemini_3}')

	response = await llm.ainvoke([UserMessage(content='What is 15 * 23? Think step by step.')])

	print(f'\nCompletion: {response.completion}')
	print(f'\nThinking present: {response.thinking is not None}')
	if response.thinking:
		print(f'Thinking length: {len(response.thinking)} chars')
		print(f'Thinking preview: {response.thinking[:300]}...')

	print(f'\nSignature present: {response.thought_signature is not None}')
	if response.thought_signature:
		print(f'Signature length: {len(response.thought_signature)} bytes')

	return response.thinking is not None and response.thought_signature is not None


async def test_agent_flow():
	"""Test full agent flow with Gemini 3."""
	print('\n' + '=' * 60)
	print('TEST 2: Agent Flow')
	print('=' * 60)

	llm = ChatGoogle(
		model='gemini-3-flash-preview',
		thinking_level='low',
	)

	browser = BrowserSession(headless=True)

	agent = Agent(
		task='Go to https://example.com and tell me the page title',
		llm=llm,
		browser=browser,
		use_thinking=True,  # No effect for Gemini 3, but shows intent
	)

	print(f'\nAgent._is_gemini_3: {agent._is_gemini_3}')
	print(f'Agent._last_thought_signature: {agent._last_thought_signature}')

	try:
		result = await agent.run(max_steps=3)

		print('\n--- Agent History ---')
		thinking_found = False
		signature_injected = False

		for i, item in enumerate(agent.history.history):
			if hasattr(item, 'model_output') and item.model_output:
				thinking = item.model_output.thinking
				print(f'\nStep {i}:')
				print(f'  Thinking present: {thinking is not None}')
				if thinking:
					thinking_found = True
					print(f'  Thinking length: {len(thinking)} chars')
					print(f'  Thinking preview: {thinking[:150]}...')

		# Check if signature was stored for next turn
		if agent._last_thought_signature:
			signature_injected = True
			print(f'\nFinal stored signature: {len(agent._last_thought_signature)} bytes')

		print(f'\n--- Result ---')
		print(f'Success: {result.is_done()}')
		print(f'Final result: {result.final_result()[:200] if result.final_result() else "None"}...')

		return thinking_found

	finally:
		await browser.kill()


async def test_multi_turn():
	"""Test multi-turn to verify signature passing."""
	print('\n' + '=' * 60)
	print('TEST 3: Multi-Turn Signature Passing')
	print('=' * 60)

	from browser_use.llm.messages import AssistantMessage, UserMessage

	llm = ChatGoogle(
		model='gemini-3-flash-preview',
		thinking_level='low',
	)

	# Turn 1
	print('\n--- Turn 1 ---')
	response1 = await llm.ainvoke([UserMessage(content='Remember the number 42. Just confirm you remember it.')])

	print(f'Response: {response1.completion[:100]}...')
	print(f'Thinking: {response1.thinking is not None}')
	print(f'Signature: {response1.thought_signature is not None}')

	if not response1.thought_signature:
		print('ERROR: No signature returned on turn 1')
		return False

	# Turn 2 - include signature from turn 1
	print('\n--- Turn 2 (with signature) ---')
	messages = [
		UserMessage(content='Remember the number 42. Just confirm you remember it.'),
		AssistantMessage(content=response1.completion, thought_signature=response1.thought_signature),
		UserMessage(content='What number did I ask you to remember?'),
	]

	response2 = await llm.ainvoke(messages)

	print(f'Response: {response2.completion[:100]}...')
	print(f'Thinking: {response2.thinking is not None}')
	print(f'Signature: {response2.thought_signature is not None}')

	# Check if model remembered
	remembered = '42' in response2.completion
	print(f'\nModel remembered 42: {remembered}')

	return remembered


async def main():
	print('Gemini 3 Thinking & Signature Test')
	print('=' * 60)

	results = {}

	try:
		results['direct_llm'] = await test_llm_directly()
	except Exception as e:
		print(f'ERROR in direct LLM test: {e}')
		results['direct_llm'] = False

	try:
		results['agent_flow'] = await test_agent_flow()
	except Exception as e:
		print(f'ERROR in agent flow test: {e}')
		results['agent_flow'] = False

	try:
		results['multi_turn'] = await test_multi_turn()
	except Exception as e:
		print(f'ERROR in multi-turn test: {e}')
		results['multi_turn'] = False

	print('\n' + '=' * 60)
	print('SUMMARY')
	print('=' * 60)
	for test, passed in results.items():
		status = 'PASS' if passed else 'FAIL'
		print(f'  {test}: {status}')

	all_passed = all(results.values())
	print(f'\nOverall: {"ALL TESTS PASSED" if all_passed else "SOME TESTS FAILED"}')

	return all_passed


if __name__ == '__main__':
	asyncio.run(main())
