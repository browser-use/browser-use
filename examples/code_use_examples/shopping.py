"""
Example: Simple product extraction with CodeAgent.

This is a simplified version demonstrating code-use mode with a smaller task:
extracting ~20 products from 2 categories on an e-commerce site.

The agent will:
- Navigate to product categories
- Extract product data using JavaScript
- Combine results from multiple categories
- Save to a JSON file
"""

import asyncio
from pathlib import Path

from lmnr import Laminar

from browser_use.code_use import CodeAgent, export_to_ipynb, session_to_python_script

Laminar.initialize()


async def main():
	"""
	Task: Extract ~20 products from 2 categories on an e-commerce site.
	"""

	task = """
Go to https://www.amazon.com and extract approximately 20 products total from these 2 categories:

1. Electronics (laptops or tablets) - 10 products
2. Home & Kitchen (small appliances) - 10 products

For each product, collect:
- Product name
- Price
- Rating (if available)
- Product URL

Save the results to a JSON file called 'simple_products.json'.
"""

	# Create code-use agent (uses ChatBrowserUse automatically)
	agent = CodeAgent(
		task=task,
		max_steps=20,
	)

	try:
		# Run the agent
		print('Running code-use agent for simple product extraction...')
		session = await agent.run()

		# Print summary
		print(f'\n{"=" * 60}')
		print('Session Summary')
		print(f'{"=" * 60}')
		print(f'Total cells executed: {len(session.cells)}')
		print(f'Total execution count: {session.current_execution_count}')

		# Print each cell
		for i, cell in enumerate(session.cells):
			print(f'\n{"-" * 60}')
			print(f'Cell {i + 1} (Status: {cell.status.value})')
			print(f'{"-" * 60}')
			print('Code:')
			print(cell.source)
			if cell.output:
				print('\nOutput:')
				print(cell.output)
			if cell.error:
				print('\nError:')
				print(cell.error)

		# Export to Jupyter notebook
		notebook_path = export_to_ipynb(session, 'simple_shopping.ipynb')
		print(f'\n✓ Exported session to Jupyter notebook: {notebook_path}')

		# Export to Python script
		script = session_to_python_script(session)
		await asyncio.to_thread(Path('simple_shopping.py').write_text, script)
		print('✓ Exported session to Python script: simple_shopping.py')

	finally:
		await agent.close()


if __name__ == '__main__':
	asyncio.run(main())
