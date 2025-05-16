import asyncio
import os
import sys
from pathlib import Path

# Ensure the project root is in the Python path if running directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI

from browser_use import Agent, Browser, BrowserConfig

# Define the task for the agent
TASK_DESCRIPTION = """
1. Go to amazon.com
2. Search for 'i7 14700k'
4. If there is an 'Add to Cart' button, open the product page and then click add to cart.
5. the open the shopping cart page /cart button/ go to cart button.
6. Scroll down to the bottom of the cart page.
7. Scroll up to the top of the cart page.
8. Finish the task.
"""

# Define the path where the Playwright script will be saved
SCRIPT_DIR = Path('./playwright_scripts')
SCRIPT_PATH = SCRIPT_DIR / 'playwright_amazon_cart_script.py'


# Helper function to stream output from the subprocess
async def stream_output(stream, prefix):
	if stream is None:
		print(f'{prefix}: (No stream available)')
		return
	while True:
		line = await stream.readline()
		if not line:
			break
		print(f'{prefix}: {line.decode().rstrip()}', flush=True)


async def main():
	# Initialize the language model
	llm = ChatOpenAI(model='gpt-4.1', temperature=0.0)

	# Configure the browser
	# Use headless=False if you want to watch the agent visually
	browser_config = BrowserConfig(headless=False)
	browser = Browser(config=browser_config)

	# Configure the agent
	# The 'save_playwright_script_path' argument tells the agent where to save the script
	agent = Agent(
		task=TASK_DESCRIPTION,
		llm=llm,
		browser=browser,
		save_playwright_script_path=str(SCRIPT_PATH),  # Pass the path as a string
	)

	print('Running the agent to generate the Playwright script...')
	history = None  # Initialize history to None
	try:
		history = await agent.run()
		print('Agent finished running.')

		if history and history.is_successful():
			print(f'Agent completed the task successfully. Final result: {history.final_result()}')
		elif history:
			print('Agent finished, but the task might not be fully successful.')
			if history.has_errors():
				print(f'Errors encountered: {history.errors()}')
		else:
			print('Agent run did not return a history object.')

	except Exception as e:
		print(f'An error occurred during the agent run: {e}')
		# Ensure browser is closed even if agent run fails
		if browser:
			await browser.close()
		return  # Exit if agent failed

	# --- Execute the Generated Playwright Script ---
	print(f'\nChecking if Playwright script was generated at: {SCRIPT_PATH}')
	if SCRIPT_PATH.exists():
		print('Playwright script found. Attempting to execute...')
		try:
			# Ensure the script directory exists before running
			SCRIPT_DIR.mkdir(parents=True, exist_ok=True)

			# Execute the generated script using asyncio.create_subprocess_exec
			process = await asyncio.create_subprocess_exec(
				sys.executable,
				str(SCRIPT_PATH),
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
				cwd=Path.cwd(),  # Run from the current working directory
			)

			print('\n--- Playwright Script Execution ---')
			# Create tasks to stream stdout and stderr concurrently
			stdout_task = asyncio.create_task(stream_output(process.stdout, 'stdout'))
			stderr_task = asyncio.create_task(stream_output(process.stderr, 'stderr'))

			# Wait for both stream tasks and the process to finish
			await asyncio.gather(stdout_task, stderr_task)
			returncode = await process.wait()
			print('-------------------------------------')

			if returncode == 0:
				print('\n✅ Playwright script executed successfully!')
			else:
				print(f'\n⚠️ Playwright script finished with exit code {returncode}.')

		except Exception as e:
			print(f'\n❌ An error occurred while executing the Playwright script: {e}')
	else:
		print(f'\n❌ Playwright script not found at {SCRIPT_PATH}. Generation might have failed.')

	# Close the browser used by the agent (if not already closed by agent.run error handling)
	# Note: The generated script manages its own browser instance.
	if browser:
		await browser.close()
		print("Agent's browser closed.")


if __name__ == '__main__':
	# Ensure the script directory is clean before running (optional)
	if SCRIPT_PATH.exists():
		SCRIPT_PATH.unlink()
		print(f'Removed existing script: {SCRIPT_PATH}')

	# Run the main async function
	asyncio.run(main())
