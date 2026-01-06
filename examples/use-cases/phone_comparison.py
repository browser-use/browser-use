import asyncio

from pydantic import BaseModel, Field

from browser_use import Agent, Browser, ChatBrowserUse


class ProductListing(BaseModel):
	"""A single product listing"""

	title: str = Field(..., description='Product title')
	url: str = Field(..., description='Full URL to listing')
	price: float = Field(..., description='Price as number')
	condition: str | None = Field(None, description='Condition: Used, New, Refurbished, etc')
	source: str = Field(..., description='Source website: Amazon, eBay, or Swappa')


class PriceComparison(BaseModel):
	"""Price comparison results"""

	search_query: str = Field(..., description='The search query used')
	listings: list[ProductListing] = Field(default_factory=list, description='All product listings')


async def find(item: str = 'Used iPhone 12'):
	"""
	Search for an item across multiple marketplaces and compare prices.

	Args:
	    item: The item to search for (e.g., "Used iPhone 12")

	Returns:
	    PriceComparison object with structured results
	"""
	browser = Browser(cdp_url='http://localhost:9222')

	llm = ChatBrowserUse()

	# Task prompt
	task = f"""
    Search for "{item}" on eBay, Amazon, and Swappa. Get any 2-3 listings from each site.

    For each site:
    1. Search for "{item}"
    2. Extract ANY 2-3 listings you find (sponsored, renewed, used - all are fine)
    3. Get: title, price (number only, if range use lower number), source, full URL, condition
    4. Move to next site

    Sites:
    - eBay: https://www.ebay.com/
    - Amazon: https://www.amazon.com/
    - Swappa: https://swappa.com/
    """

	# Create agent with structured output
	agent = Agent(
		browser=browser,
		llm=llm,
		task=task,
		output_model_schema=PriceComparison,
	)

	# Run the agent
	result = await agent.run()
	return result


if __name__ == '__main__':
	# Get user input
	query = input('What item would you like to compare prices for? ').strip()
	if not query:
		query = 'Used iPhone 12'
		print(f'Using default query: {query}')

	result = asyncio.run(find(query))

	# Access structured output
	if result and result.structured_output:
		comparison = result.structured_output

		print(f'\n{"=" * 60}')
		print(f'Price Comparison Results: {comparison.search_query}')
		print(f'{"=" * 60}\n')

		for listing in comparison.listings:
			print(f'Title: {listing.title}')
			print(f'Price: ${listing.price}')
			print(f'Source: {listing.source}')
			print(f'URL: {listing.url}')
			print(f'Condition: {listing.condition or "N/A"}')
			print(f'{"-" * 60}')
