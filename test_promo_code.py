#!/usr/bin/env python3
"""
Test script for finding and documenting promo code application process on any website.

Usage:
	python test_promo_code.py <website_url>

Example:
	python test_promo_code.py "https://example-store.com"

Output:
	- Creates a timestamped folder in ./promo_code_tests/
	- Saves guide, thoughts, and screenshots to the folder
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from browser_use import Agent, Browser, BrowserProfile


async def test_promo_code_application(website: str):
	"""
	Test promo code application on a website and document the process.

	Args:
		website: The website URL to test
	"""
	# Create output directory
	timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
	output_dir = Path('./promo_code_tests') / f'{timestamp}_{website.replace("https://", "").replace("http://", "").replace("/", "_")[:50]}'
	output_dir.mkdir(parents=True, exist_ok=True)

	print(f'\n🔍 Testing promo code application on: {website}')
	print(f'📁 Output directory: {output_dir}\n')

	# Create browser profile with screenshot saving
	profile = BrowserProfile(
		headless=False,  # Show browser for debugging
		downloads_path=str(output_dir / 'downloads'),
		highlight_elements=True,
		post_interaction_settle_time=0.8,  # Slightly longer for reliability
	)

	# Initialize browser
	browser = Browser(profile=profile)

	# Import LLM - use environment variable or default
	try:
		from langchain_openai import ChatOpenAI

		llm = ChatOpenAI(model='gpt-4o')
	except ImportError:
		print('⚠️  langchain_openai not installed. Trying anthropic...')
		try:
			from langchain_anthropic import ChatAnthropic

			llm = ChatAnthropic(model='claude-sonnet-4-5-20250929')
		except ImportError:
			print('❌ No LLM library found. Please install langchain-openai or langchain-anthropic')
			sys.exit(1)

	# Create task
	task = f"""Find out how to apply a promo code on {website} using the code SAVE10 and write a short guide how to do it.

Your guide should include:
1. Step-by-step instructions
2. Where to find the promo code field
3. When in the checkout process to apply it
4. What to look for to confirm it worked

Be specific and include details like button names, field labels, etc."""

	try:
		# Track agent history for capturing thoughts
		agent_history = []

		# Create agent with step callback to capture thoughts and screenshots
		async def capture_step(step_info):
			"""Callback to capture each step's information."""
			agent_history.append(
				{
					'step': step_info.step_number,
					'thinking': getattr(step_info.model_output, 'current_state', {}).get('thinking', '')
					if hasattr(step_info, 'model_output') and step_info.model_output
					else '',
					'action': str(getattr(step_info.model_output, 'action', ''))
					if hasattr(step_info, 'model_output') and step_info.model_output
					else '',
				}
			)

		# Create and run agent
		agent = Agent(
			task=task,
			llm=llm,
			browser=browser,
			register_new_step_callback=capture_step,
		)

		# Run agent
		result = await agent.run()

		# Save guide
		guide_path = output_dir / 'guide.txt'
		with open(guide_path, 'w') as f:
			f.write(f'Promo Code Application Guide for {website}\n')
			f.write('=' * 60 + '\n\n')
			if result and hasattr(result, 'extracted_content'):
				f.write(result.extracted_content or 'No guide generated')
			else:
				f.write(str(result))
		print(f'✅ Guide saved to: {guide_path}')

		# Save thoughts
		thoughts_path = output_dir / 'thoughts.json'
		with open(thoughts_path, 'w') as f:
			json.dump(
				{
					'website': website,
					'timestamp': timestamp,
					'agent_history': agent_history,
					'total_steps': len(agent_history),
				},
				f,
				indent=2,
			)
		print(f'✅ Thoughts saved to: {thoughts_path}')

		# Save formatted thoughts as readable text
		thoughts_txt_path = output_dir / 'thoughts.txt'
		with open(thoughts_txt_path, 'w') as f:
			f.write(f'Agent Reasoning for {website}\n')
			f.write('=' * 60 + '\n\n')
			for entry in agent_history:
				f.write(f"\nStep {entry['step']}:\n")
				f.write('-' * 40 + '\n')
				if entry.get('thinking'):
					f.write(f"Thinking: {entry['thinking']}\n\n")
				if entry.get('action'):
					f.write(f"Action: {entry['action']}\n")
				f.write('\n')
		print(f'✅ Formatted thoughts saved to: {thoughts_txt_path}')

		# Check for screenshots in agent history
		screenshot_count = 0
		if hasattr(agent, 'history') and agent.history:
			for i, history_item in enumerate(agent.history):
				if hasattr(history_item, 'state') and hasattr(history_item.state, 'screenshot'):
					screenshot = history_item.state.screenshot
					if screenshot:
						screenshot_path = output_dir / f'screenshot_step_{i + 1}.png'
						# Screenshot is base64 encoded
						import base64

						try:
							screenshot_data = base64.b64decode(screenshot)
							with open(screenshot_path, 'wb') as f:
								f.write(screenshot_data)
							screenshot_count += 1
						except Exception as e:
							print(f'⚠️  Failed to save screenshot {i + 1}: {e}')

		print(f'✅ Saved {screenshot_count} screenshots')

		# Create summary file
		summary_path = output_dir / 'summary.txt'
		with open(summary_path, 'w') as f:
			f.write(f'Promo Code Test Summary\n')
			f.write('=' * 60 + '\n\n')
			f.write(f'Website: {website}\n')
			f.write(f'Timestamp: {timestamp}\n')
			f.write(f'Total Steps: {len(agent_history)}\n')
			f.write(f'Screenshots: {screenshot_count}\n')
			f.write(f'\nOutput Files:\n')
			f.write(f'  - guide.txt: Step-by-step guide for applying promo code\n')
			f.write(f'  - thoughts.txt: Agent reasoning for each step\n')
			f.write(f'  - thoughts.json: Structured agent history data\n')
			f.write(f'  - screenshot_step_N.png: Screenshots from each step\n')
		print(f'✅ Summary saved to: {summary_path}')

		print(f'\n✅ All outputs saved to: {output_dir}')
		print(f'\n📋 Quick view:')
		print(f'   Guide:    cat {guide_path}')
		print(f'   Thoughts: cat {thoughts_txt_path}')
		print(f'   Summary:  cat {summary_path}')

		return result

	except Exception as e:
		print(f'\n❌ Error during test: {e}')
		# Save error info
		error_path = output_dir / 'error.txt'
		with open(error_path, 'w') as f:
			f.write(f'Error occurred during promo code test\n')
			f.write('=' * 60 + '\n\n')
			f.write(f'Website: {website}\n')
			f.write(f'Error: {str(e)}\n\n')
			import traceback

			f.write(f'Traceback:\n{traceback.format_exc()}')
		print(f'❌ Error details saved to: {error_path}')
		raise

	finally:
		# Close browser
		await browser.close()


def main():
	"""Main entry point."""
	if len(sys.argv) < 2:
		print('Usage: python test_promo_code.py <website_url>')
		print('\nExample:')
		print('  python test_promo_code.py "https://example-store.com"')
		sys.exit(1)

	website = sys.argv[1]

	# Ensure URL has protocol
	if not website.startswith('http://') and not website.startswith('https://'):
		website = 'https://' + website

	# Run the test
	asyncio.run(test_promo_code_application(website))


if __name__ == '__main__':
	main()
