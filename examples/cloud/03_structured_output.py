"""
Cloud Example 3: Structured JSON Output 📋
==========================================

This example demonstrates how to get structured, validated JSON output:
- Define Pydantic schemas for type safety
- Extract structured data from websites
- Validate and parse JSON responses
- Handle different data types and nested structures

Perfect for: Data extraction, API integration, structured analysis

Cost: ~$0.06 (1 task + 5-6 steps with GPT-4.1 mini)
"""

import argparse
import json
import os
import time
from typing import Any

import requests
from pydantic import BaseModel, Field, ValidationError
from requests.exceptions import RequestException

# Configuration
API_KEY = os.getenv('BROWSER_USE_API_KEY')
if not API_KEY:
	raise ValueError('Please set BROWSER_USE_API_KEY environment variable')

BASE_URL = os.getenv('BROWSER_USE_BASE_URL', 'https://api.browser-use.com/api/v1')
TIMEOUT = int(os.getenv('BROWSER_USE_TIMEOUT', '30'))
HEADERS = {'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'}


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
	"""Make HTTP request with timeout and retry logic."""
	kwargs.setdefault('timeout', TIMEOUT)

	for attempt in range(3):
		try:
			response = requests.request(method, url, **kwargs)
			response.raise_for_status()
			return response
		except RequestException as e:
			if attempt == 2:  # Last attempt
				raise
			sleep_time = 2**attempt
			print(f'⚠️  Request failed (attempt {attempt + 1}/3), retrying in {sleep_time}s: {e}')
			time.sleep(sleep_time)

	raise RuntimeError('Unexpected error in retry logic')


# Define structured output schemas using Pydantic
class NewsArticle(BaseModel):
	"""Schema for a news article."""

	title: str = Field(description='The headline of the article')
	summary: str = Field(description='Brief summary of the article')
	url: str = Field(description='Direct link to the article')
	published_date: str | None = Field(description='Publication date if available')
	category: str | None = Field(description='Article category/section')


class NewsResponse(BaseModel):
	"""Schema for multiple news articles."""

	articles: list[NewsArticle] = Field(description='List of news articles')
	source_website: str = Field(description='The website where articles were found')
	extracted_at: str = Field(description='When the data was extracted')


class ProductInfo(BaseModel):
	"""Schema for product information."""

	name: str = Field(description='Product name')
	price: float = Field(description='Product price in USD')
	rating: float | None = Field(description='Average rating (0-5 scale)')
	availability: str = Field(description='Stock status (in stock, out of stock, etc.)')
	description: str = Field(description='Product description')


class CompanyInfo(BaseModel):
	"""Schema for company information."""

	name: str = Field(description='Company name')
	stock_symbol: str | None = Field(description='Stock ticker symbol')
	market_cap: str | None = Field(description='Market capitalization')
	industry: str = Field(description='Primary industry')
	headquarters: str = Field(description='Headquarters location')
	founded_year: int | None = Field(description='Year founded')


def create_structured_task(instructions: str, schema_model: type[BaseModel], **kwargs) -> str:
	"""
	Create a task that returns structured JSON output.

	Args:
	    instructions: Task description
	    schema_model: Pydantic model defining the expected output structure
	    **kwargs: Additional task parameters

	Returns:
	    task_id: Unique identifier for the created task
	"""
	print(f'📝 Creating structured task: {instructions}')
	print(f'🏗️  Expected schema: {schema_model.__name__}')

	# Generate JSON schema from Pydantic model
	json_schema = schema_model.model_json_schema()

	payload = {
		'task': instructions,
		'structured_output_json': json.dumps(json_schema),
		'llm_model': 'gpt-4.1-mini',
		'max_agent_steps': 15,
		'enable_public_share': True,  # Enable shareable execution URLs
		**kwargs,
	}

	response = _request_with_retry('post', f'{BASE_URL}/run-task', headers=HEADERS, json=payload)

	task_id = response.json()['id']
	print(f'✅ Structured task created: {task_id}')
	return task_id


def wait_for_structured_completion(task_id: str, max_wait_time: int = 300) -> dict[str, Any]:
	"""Wait for task completion and return the result."""
	print(f'⏳ Waiting for structured output (max {max_wait_time}s)...')

	start_time = time.time()

	while True:
		response = _request_with_retry('get', f'{BASE_URL}/task/{task_id}/status', headers=HEADERS)
		status = response.json()
		elapsed = time.time() - start_time

		# Check for timeout
		if elapsed > max_wait_time:
			print(f'\r⏰ Task timeout after {max_wait_time}s - stopping wait' + ' ' * 30)
			# Get final details before timeout
			details_response = _request_with_retry('get', f'{BASE_URL}/task/{task_id}', headers=HEADERS)
			details = details_response.json()
			return details

		# Get step count from full details for better progress tracking
		details_response = _request_with_retry('get', f'{BASE_URL}/task/{task_id}', headers=HEADERS)
		details = details_response.json()
		steps = len(details.get('steps', []))

		# Build status message
		if status == 'running':
			status_msg = f'📋 Structured task | Step {steps} | ⏱️  {elapsed:.0f}s | 🔄 Extracting...'
		else:
			status_msg = f'📋 Structured task | Step {steps} | ⏱️  {elapsed:.0f}s | Status: {status}'

		# Clear line and show status
		print(f'\r{status_msg:<80}', end='', flush=True)

		if status == 'finished':
			print(f'\r✅ Structured data extracted! ({steps} steps in {elapsed:.1f}s)' + ' ' * 20)
			return details

		elif status in ['failed', 'stopped']:
			print(f'\r❌ Task {status} after {steps} steps' + ' ' * 30)
			return details

		time.sleep(3)


def validate_and_display_output(output: str, schema_model: type[BaseModel]):
	"""
	Validate the JSON output against the schema and display results.

	Args:
	    output: Raw JSON string from the task
	    schema_model: Pydantic model for validation
	"""
	print('\n📊 Structured Output Analysis')
	print('=' * 40)

	try:
		# Parse and validate the JSON
		parsed_data = schema_model.model_validate_json(output)
		print('✅ JSON validation successful!')

		# Pretty print the structured data
		print('\n📋 Parsed Data:')
		print('-' * 20)
		print(parsed_data.model_dump_json(indent=2))

		# Display specific fields based on model type
		if isinstance(parsed_data, NewsResponse):
			print(f'\n📰 Found {len(parsed_data.articles)} articles from {parsed_data.source_website}')
			for i, article in enumerate(parsed_data.articles[:3], 1):
				print(f'\n{i}. {article.title}')
				print(f'   Summary: {article.summary[:100]}...')
				print(f'   URL: {article.url}')

		elif isinstance(parsed_data, ProductInfo):
			print(f'\n🛍️  Product: {parsed_data.name}')
			print(f'   Price: ${parsed_data.price}')
			print(f'   Rating: {parsed_data.rating}/5' if parsed_data.rating else '   Rating: N/A')
			print(f'   Status: {parsed_data.availability}')

		elif isinstance(parsed_data, CompanyInfo):
			print(f'\n🏢 Company: {parsed_data.name}')
			print(f'   Industry: {parsed_data.industry}')
			print(f'   Headquarters: {parsed_data.headquarters}')
			if parsed_data.founded_year:
				print(f'   Founded: {parsed_data.founded_year}')

		return parsed_data

	except ValidationError as e:
		print('❌ JSON validation failed!')
		print(f'Errors: {e}')
		print(f'\nRaw output: {output[:500]}...')
		return None

	except json.JSONDecodeError as e:
		print('❌ Invalid JSON format!')
		print(f'Error: {e}')
		print(f'\nRaw output: {output[:500]}...')
		return None


def demo_news_extraction():
	"""Demo: Extract structured news data."""
	print('\n📰 Demo 1: News Article Extraction')
	print('-' * 40)

	task = """
    Go to a major news website (like BBC, CNN, or Reuters) and extract information 
    about the top 3 news articles. For each article, get the title, summary, URL, 
    and any other available metadata.
    """

	task_id = create_structured_task(task, NewsResponse)
	result = wait_for_structured_completion(task_id)

	if result.get('output'):
		parsed_result = validate_and_display_output(result['output'], NewsResponse)

		# Show execution URLs
		if result.get('live_url'):
			print(f'\n🔗 Live Preview: {result["live_url"]}')
		if result.get('public_share_url'):
			print(f'🌐 Share URL: {result["public_share_url"]}')
		elif result.get('share_url'):
			print(f'🌐 Share URL: {result["share_url"]}')

		return parsed_result
	else:
		print('❌ No structured output received')
		return None


def demo_product_extraction():
	"""Demo: Extract structured product data."""
	print('\n🛍️  Demo 2: Product Information Extraction')
	print('-' * 40)

	task = """
    Go to Amazon and search for 'wireless headphones'. Find the first product result 
    and extract detailed information including name, price, rating, availability, 
    and description.
    """

	task_id = create_structured_task(task, ProductInfo)
	result = wait_for_structured_completion(task_id)

	if result.get('output'):
		parsed_result = validate_and_display_output(result['output'], ProductInfo)

		# Show execution URLs
		if result.get('live_url'):
			print(f'\n🔗 Live Preview: {result["live_url"]}')
		if result.get('public_share_url'):
			print(f'🌐 Share URL: {result["public_share_url"]}')
		elif result.get('share_url'):
			print(f'🌐 Share URL: {result["share_url"]}')

		return parsed_result
	else:
		print('❌ No structured output received')
		return None


def demo_company_extraction():
	"""Demo: Extract structured company data."""
	print('\n🏢 Demo 3: Company Information Extraction')
	print('-' * 40)

	task = """
    Go to a financial website and look up information about Apple Inc. 
    Extract company details including name, stock symbol, market cap, 
    industry, headquarters, and founding year.
    """

	task_id = create_structured_task(task, CompanyInfo)
	result = wait_for_structured_completion(task_id)

	if result.get('output'):
		parsed_result = validate_and_display_output(result['output'], CompanyInfo)

		# Show execution URLs
		if result.get('live_url'):
			print(f'\n🔗 Live Preview: {result["live_url"]}')
		if result.get('public_share_url'):
			print(f'🌐 Share URL: {result["public_share_url"]}')
		elif result.get('share_url'):
			print(f'🌐 Share URL: {result["share_url"]}')

		return parsed_result
	else:
		print('❌ No structured output received')
		return None


def main():
	"""Demonstrate structured output extraction."""
	print('📋 Browser Use Cloud - Structured JSON Output')
	print('=' * 50)

	print('🎯 Features:')
	print('• Type-safe Pydantic schemas')
	print('• Automatic JSON validation')
	print('• Structured data extraction')
	print('• Multiple output formats')

	try:
		# Parse command line arguments
		parser = argparse.ArgumentParser(description='Structured output extraction demo')
		parser.add_argument('--demo', choices=['news', 'product', 'company', 'all'], default='news', help='Which demo to run')
		args = parser.parse_args()

		print(f'\n🔍 Running {args.demo} demo(s)...')

		if args.demo == 'news':
			demo_news_extraction()
		elif args.demo == 'product':
			demo_product_extraction()
		elif args.demo == 'company':
			demo_company_extraction()
		elif args.demo == 'all':
			demo_news_extraction()
			demo_product_extraction()
			demo_company_extraction()

	except requests.exceptions.RequestException as e:
		print(f'❌ API Error: {e}')
	except Exception as e:
		print(f'❌ Error: {e}')


if __name__ == '__main__':
	main()
