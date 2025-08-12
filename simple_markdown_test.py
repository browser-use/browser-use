#!/usr/bin/env python3
"""
Simple interactive test for HTML-to-markdown conversion.
Tests the exact conversion logic from extract_structured_data on real websites.
"""

import asyncio
import re
from datetime import datetime

from playwright.async_api import async_playwright


class SimpleMarkdownTester:
	"""Test HTML-to-markdown conversion on real websites using Playwright directly."""

	def __init__(self):
		self.test_websites = [
			'https://example.com',
			'https://archive.org',
			'https://en.wikipedia.org/wiki/Internet',
			'https://github.com',
			'https://stackoverflow.com',
			'https://developer.mozilla.org/en-US/docs/Web/HTML',
			'https://news.ycombinator.com',
			'https://reddit.com',
			'https://semantic-ui.com/modules/dropdown.html',
			'https://www.google.com',
		]
		self.current_index = 0
		self.browser = None
		self.page = None

	async def start_browser(self):
		"""Start Playwright browser."""
		playwright = await async_playwright().start()
		self.browser = await playwright.chromium.launch(headless=False)
		self.page = await self.browser.new_page()
		print('🌐 Browser started successfully')

	async def close_browser(self):
		"""Close browser."""
		if self.browser:
			await self.browser.close()
			print('🔒 Browser closed')

	async def extract_html(self, url: str) -> str:
		"""Extract HTML content from URL."""
		try:
			print(f'📄 Loading {url}...')
			if self.page:
				await self.page.goto(url, wait_until='domcontentloaded')

			# Wait for page to load
			await asyncio.sleep(3)

			# Get the HTML content (same method as extract_structured_data)
			if self.page:
				html_content = await self.page.content()
			else:
				return '<html><body>Page not initialized</body></html>'

			return html_content

		except Exception as e:
			print(f'❌ Error extracting HTML from {url}: {e}')
			return f'<html><body>Error: {e}</body></html>'

	def convert_to_markdown(self, page_html: str, extract_links: bool = False) -> tuple[str, str]:
		"""
		Convert HTML to markdown using the exact same method as extract_structured_data.
		Returns (original_markdown, cleaned_markdown)
		"""
		try:
			import markdownify

			# Simple one-liner conversion
			if extract_links:
				markdown = markdownify.markdownify(page_html)
			else:
				# Convert but keep link text, just remove the URLs
				markdown = markdownify.markdownify(page_html)
				markdown = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', markdown)

			return markdown, markdown

		except Exception as e:
			error_msg = f'Markdown conversion error: {e}'
			return error_msg, error_msg

	def analyze_content(self, original: str, cleaned: str, url: str) -> dict:
		"""Analyze the markdown content quality."""
		analysis = {
			'url': url,
			'original_length': len(original),
			'cleaned_length': len(cleaned),
			'chars_removed': len(original) - len(cleaned),
			'reduction_percentage': ((len(original) - len(cleaned)) / len(original)) * 100 if len(original) > 0 else 0,
			'word_count': len(cleaned.split()),
			'line_count': len(cleaned.split('\n')),
			'has_substantial_content': len(cleaned.strip()) > 100,
			'has_headings': '#' in cleaned,
			'has_images': '![' in cleaned,
			'images_count': len(re.findall(r'!\[.*?\]\([^)]*\)', cleaned)),
			'links_count': len(re.findall(r'\[.*?\]\([^)]*\)', cleaned)),
			'preview': cleaned[:500] + '...' if len(cleaned) > 500 else cleaned,
		}
		return analysis

	def print_analysis(self, analysis: dict):
		"""Print content analysis in a readable format."""
		print(f'\n📊 Analysis for {analysis["url"]}')
		print('=' * 80)
		print('📏 Content Length:')
		print(f'   Original: {analysis["original_length"]:,} chars')
		print(f'   Cleaned:  {analysis["cleaned_length"]:,} chars')
		print(f'   Removed:  {analysis["chars_removed"]:,} chars ({analysis["reduction_percentage"]:.1f}%)')

		print('\n📝 Content Stats:')
		print(f'   Words: {analysis["word_count"]:,}')
		print(f'   Lines: {analysis["line_count"]:,}')
		print(f'   Images: {analysis["images_count"]}')
		print(f'   Links: {analysis["links_count"]}')

		print('\n✅ Quality Indicators:')
		print(f'   Substantial content: {"✅" if analysis["has_substantial_content"] else "❌"}')
		print(f'   Has headings: {"✅" if analysis["has_headings"] else "❌"}')
		print(f'   Has images: {"✅" if analysis["has_images"] else "❌"}')

		print('\n📖 Content Preview (first 500 chars):')
		print('-' * 80)
		print(analysis['preview'])
		print('-' * 80)

	async def test_current_website(self, extract_links: bool = False):
		"""Test the current website in the list."""
		if self.current_index >= len(self.test_websites):
			print('🏁 Reached end of website list')
			return

		url = self.test_websites[self.current_index]
		print(f'\n🔍 Testing website {self.current_index + 1}/{len(self.test_websites)}: {url}')

		# Extract HTML
		html_content = await self.extract_html(url)

		# Convert to markdown
		original_markdown, cleaned_markdown = self.convert_to_markdown(html_content, extract_links)

		# Analyze results
		analysis = self.analyze_content(original_markdown, cleaned_markdown, url)

		# Display results
		self.print_analysis(analysis)

		return analysis

	async def run_interactive_test(self):
		"""Run interactive test session."""
		print('🧪 Simple Markdown Conversion Tester')
		print('=' * 60)
		print('Commands:')
		print('  ENTER - Test current website again')
		print('  n     - Next website')
		print('  p     - Previous website')
		print('  l     - Toggle extract_links mode')
		print('  s     - Save current result')
		print('  q     - Quit')
		print('=' * 60)

		await self.start_browser()

		extract_links = False

		try:
			while True:
				print(
					f'\nCurrent website: {self.current_index + 1}/{len(self.test_websites)} - {self.test_websites[self.current_index]}'
				)
				print(f'Extract links mode: {"ON" if extract_links else "OFF"}')

				command = input('\nCommand (ENTER/n/p/l/s/q): ').strip().lower()

				if command == 'q':
					break
				elif command == 'n':
					self.current_index = min(self.current_index + 1, len(self.test_websites) - 1)
					continue
				elif command == 'p':
					self.current_index = max(self.current_index - 1, 0)
					continue
				elif command == 'l':
					extract_links = not extract_links
					print(f'Extract links mode: {"ON" if extract_links else "OFF"}')
					continue
				elif command == 's':
					# Save current result
					analysis = await self.test_current_website(extract_links)
					if analysis:
						timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
						filename = f'markdown_test_{timestamp}.txt'
						with open(filename, 'w', encoding='utf-8') as f:
							f.write(f'URL: {analysis["url"]}\n')
							f.write(f'Timestamp: {timestamp}\n')
							f.write(f'Extract links: {extract_links}\n')
							f.write(f'Content length: {analysis["cleaned_length"]} chars\n')
							f.write('=' * 60 + '\n')
							f.write(analysis['preview'])
						print(f'💾 Analysis saved to {filename}')
					continue
				elif command == '' or command == 'enter':
					# Test current website
					await self.test_current_website(extract_links)
				else:
					print('❓ Unknown command. Use ENTER/n/p/l/s/q')

		except KeyboardInterrupt:
			print('\n🛑 Interrupted by user')
		except Exception as e:
			print(f'❌ Error during interactive test: {e}')
		finally:
			await self.close_browser()


async def main():
	"""Run the interactive markdown conversion test."""
	tester = SimpleMarkdownTester()
	await tester.run_interactive_test()


if __name__ == '__main__':
	print('🚀 Starting Simple Markdown Conversion Tester')
	print('This tests the exact HTML-to-markdown conversion used in extract_structured_data')
	print('Press Enter to start, then use commands to navigate through websites')
	input('Press Enter to continue...')
	asyncio.run(main())
