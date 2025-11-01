"""
Example: Using code-use mode to extract products from multiple pages.

This example demonstrates the new code-use mode, which works like a Jupyter notebook
where the LLM writes Python code that gets executed in a persistent namespace.

The agent can:
- Navigate to pages
- Extract data using JavaScript
- Combine results from multiple pages
- Save data to files
- Export the session as a Jupyter notebook

This solves the problem from the brainstorm where extraction of multiple items
was difficult with the extract tool alone.
"""

import asyncio

from lmnr import Laminar

from browser_use.code_use import CodeAgent

Laminar.initialize()


async def main():
	task = """

Go to https://www.flipkart.com. Continue collecting products from Flipkart in the following categories. I need approximately 50 products from:\n\n1. Books & Media (books, stationery) - 15 products\n2. Sports & Fitness (equipment, clothing, accessories) - 15 products  \n3. Beauty & Personal Care (cosmetics, skincare, grooming) - 10 products\nAnd 2 other categories you find interesting.\nNavigate to these categories and collect products with:\n- Product URL (working link)\n- Product name/description\n- Actual price (MRP)\n- Deal price (current selling price)  \n- Discount percentage\n\nFocus on products with good discounts and clear pricing. Target around 40 products total from these three categories.

	"""
	# Create code-use agent (uses ChatBrowserUse automatically)
	agent = CodeAgent(
		task=task,
		max_steps=30,
	)

	try:
		# Run the agent
		print('Running code-use agent...')
		session = await agent.run()

	finally:
		await agent.close()


if __name__ == '__main__':
	asyncio.run(main())
