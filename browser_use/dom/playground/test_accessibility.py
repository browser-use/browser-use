"""
Accessibility Tree Playground for browser-use

- Launches a browser and navigates to a target URL (default: amazon.com)
- Extracts both the full and interesting-only accessibility trees using Playwright
- Prints and saves both trees to JSON files
- Recursively prints relevant info for each node (role, name, value, description, focusable, focused, checked, selected, disabled, children count)
- Explains the difference between the accessibility tree and the DOM tree
- Notes on React/Vue/SPA apps
- Easy to modify for your own experiments

Run with: python browser_use/dom/tests/test_accessibility_playground.py
"""

import asyncio

from browser_use.browser.types import async_playwright

# Change this to any site you want to test


# Helper to recursively print relevant info from the accessibility tree
def print_ax_tree(node, depth=0):
	if not node:
		return
	indent = '  ' * depth
	info = [
		f'role={node.get("role")!r}',
		f'name={node.get("name")!r}' if node.get('name') else None,
		f'value={node.get("value")!r}' if node.get('value') else None,
		f'desc={node.get("description")!r}' if node.get('description') else None,
		f'focusable={node.get("focusable")!r}' if 'focusable' in node else None,
		f'focused={node.get("focused")!r}' if 'focused' in node else None,
		f'checked={node.get("checked")!r}' if 'checked' in node else None,
		f'selected={node.get("selected")!r}' if 'selected' in node else None,
		f'disabled={node.get("disabled")!r}' if 'disabled' in node else None,
		f'children={len(node.get("children", []))}' if node.get('children') else None,
	]
	print('--------------------------------')
	print(indent + ', '.join([x for x in info if x]))
	for child in node.get('children', []):
		print_ax_tree(child, depth + 1)


# Helper to print all available accessibility node attributes
# Prints all key-value pairs for each node (except 'children'), then recurses into children
def print_all_fields(node, depth=0):
	if not node:
		return
	indent = '  ' * depth
	for k, v in node.items():
		if k != 'children':
			print(f'{indent}{k}: {v!r}')
	if 'children' in node:
		print(f'{indent}children: {len(node["children"])}')
		for child in node['children']:
			print_all_fields(child, depth + 1)


def flatten_ax_tree(node, lines):
	if not node:
		return
	role = node.get('role', '')
	name = node.get('name', '')
	lines.append(f'{role} {name}')
	for child in node.get('children', []):
		flatten_ax_tree(child, lines)


async def get_ax_tree(TARGET_URL):
	async with async_playwright() as p:
		browser = await p.chromium.launch(headless=True)
		page = await browser.new_page()
		print(f'Navigating to {TARGET_URL}')
		await page.goto(TARGET_URL, wait_until='domcontentloaded')

		ax_tree_interesting = await page.accessibility.snapshot(interesting_only=True)
		lines = []
		flatten_ax_tree(ax_tree_interesting, lines)
		print(lines)
		print(f'length of ax_tree_interesting: {len(lines)}')

		await browser.close()


if __name__ == '__main__':
	TARGET_URL = [
		# 'https://amazon.com/',
		# 'https://www.google.com/',
		# 'https://www.facebook.com/',
		# 'https://platform.openai.com/tokenizer',
		'https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input/checkbox',
	]
	for url in TARGET_URL:
		asyncio.run(get_ax_tree(url))
