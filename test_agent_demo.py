"""
Test script for the new features:
1. Account management
2. Product recommendation
3. GitHub navigation

Setup:
  1. Create a .env file with your LLM API key:
     OPENAI_API_KEY=sk-...
     or
     ANTHROPIC_API_KEY=sk-ant-...

  2. Edit accounts.json with your real credentials (optional)

  3. Run:
     uv run python test_agent_demo.py
"""

import asyncio

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent


async def test_github_navigation():
	"""Test: GitHub repo navigation and code search"""
	print("\n" + "=" * 60)
	print("TEST: GitHub Navigation")
	print("=" * 60)

	agent = Agent(
		task=(
			"Go to the browser-use/browser-use repository on GitHub. "
			"Find the file browser_use/accounts/service.py and tell me "
			"what the AccountService class does."
		),
		accounts_file="./accounts.json",
	)
	result = await agent.run(max_steps=10)
	print(f"\nResult: {result.final_result()}")


async def test_product_recommendation():
	"""Test: Product recommendation on a shopping site"""
	print("\n" + "=" * 60)
	print("TEST: Product Recommendation")
	print("=" * 60)

	agent = Agent(
		task=(
			"Go to amazon.com, search for 'wireless mouse under $30', "
			"and recommend the best 3 options based on ratings and price. "
			"Explain why you recommend each one."
		),
		accounts_file="./accounts.json",
	)
	result = await agent.run(max_steps=15)
	print(f"\nResult: {result.final_result()}")


async def test_account_loading():
	"""Test: Account loading and credential injection"""
	print("\n" + "=" * 60)
	print("TEST: Account Management")
	print("=" * 60)

	agent = Agent(
		task=(
			"Use the 'My GitHub' account to log in to github.com. "
			"After login, tell me what repositories are visible."
		),
		accounts_file="./accounts.json",
	)
	result = await agent.run(max_steps=10)
	print(f"\nResult: {result.final_result()}")


async def main():
	print("Browser-Use Enhanced Agent Test")
	print("Choose a test to run:")
	print("  1. GitHub Navigation (search code in a repo)")
	print("  2. Product Recommendation (amazon)")
	print("  3. Account Management (login with stored credentials)")
	print("  4. Run all tests")
	print()

	choice = input("Enter choice (1-4): ").strip()

	if choice == "1":
		await test_github_navigation()
	elif choice == "2":
		await test_product_recommendation()
	elif choice == "3":
		await test_account_loading()
	elif choice == "4":
		await test_github_navigation()
		await test_product_recommendation()
		await test_account_loading()
	else:
		print("Invalid choice")


if __name__ == "__main__":
	asyncio.run(main())
