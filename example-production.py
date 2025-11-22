"""
PRODUCTION EXAMPLE - Login to sites and do tasks

This example shows how to:
- Enable vision so the agent can SEE the page
- Give clear instructions
- Handle logins
- Do real work after logging in
- Debug when things go wrong
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

# Load API key
env_path = Path.home() / '.env'
if env_path.exists():
	load_dotenv(env_path)
else:
	load_dotenv()

from browser_use import Agent, Controller
from langchain_anthropic import ChatAnthropic

# IMPORTANT: Use Sonnet for complex tasks like logins!
# Haiku is cheap but struggles with complex multi-step tasks
llm = ChatAnthropic(
	model_name='claude-3-5-sonnet-20240620',  # More capable for logins
	temperature=0.0,
	timeout=60,
)

# For simple tasks, you can use Haiku to save money:
# llm = ChatAnthropic(model_name='claude-haiku-4-5-20251001', temperature=0.0)


async def main():
	print('🤖 Starting browser automation agent...\n')

	# ═══════════════════════════════════════
	# EXAMPLE 1: Login to a site
	# ═══════════════════════════════════════

	task = """
	Go to facebook.com

	If I'm not logged in:
	1. Click the login button
	2. Enter username: myemail@example.com
	3. Enter password: mypassword123
	4. Click the login button
	5. Wait for the page to load

	Once logged in:
	- Navigate to my profile
	- Tell me how many friends I have
	"""

	# ═══════════════════════════════════════
	# EXAMPLE 2: Fill out a form
	# ═══════════════════════════════════════

	# task = """
	# Go to https://example.com/contact-form
	#
	# Fill out the contact form with:
	# - Name: John Smith
	# - Email: john@example.com
	# - Phone: 555-1234
	# - Message: I'm interested in your services
	#
	# Then click Submit
	# Wait for the confirmation message and tell me what it says
	# """

	# ═══════════════════════════════════════
	# EXAMPLE 3: Research and collect data
	# ═══════════════════════════════════════

	# task = """
	# Go to Amazon.com
	# Search for "wireless mouse"
	# Sort by customer reviews (highest rated)
	# Get the names and prices of the top 5 results
	# Save this information to a file called mouse_prices.txt
	# """

	print(f'📋 Task: {task}\n')
	print('=' * 60)

	agent = Agent(
		task=task,
		llm=llm,
		use_vision=True,  # CRITICAL! This lets the agent SEE the page
		max_actions_per_step=10,  # Allow more actions per step
		save_conversation_path='./agent_conversation.json',  # Save for debugging
	)

	try:
		result = await agent.run(max_steps=30)  # Increase from default 10

		print('\n' + '=' * 60)
		print('✅ Task completed!')
		print(f'\n📊 Result: {result}')

	except Exception as e:
		print('\n' + '=' * 60)
		print(f'❌ Error occurred: {e}')
		print('\n💡 Check agent_conversation.json to see what happened')


if __name__ == '__main__':
	asyncio.run(main())
