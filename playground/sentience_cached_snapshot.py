"""
Advanced example: Sentience CachedSnapshot for efficient action loops.

This example demonstrates:
1. Using CachedSnapshot to reduce redundant snapshot calls
2. The invalidate() pattern after DOM-modifying actions
3. Scrolling and finding elements across multiple snapshots
4. Element grounding with BBox coordinates

Requirements:
    pip install browser-use sentienceapi

Usage:
    python playground/sentience_cached_snapshot.py
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from browser_use.browser import BrowserProfile, BrowserSession

# Sentience SDK imports
from sentience import find, get_extension_dir, query
from sentience.backends import (
	BrowserUseAdapter,
	CachedSnapshot,
	ExtensionNotLoadedError,
	click,
	scroll,
	snapshot,
	type_text,
)


async def main():
	"""Demo: CachedSnapshot for efficient element grounding."""

	extension_path = get_extension_dir()
	print(f"Sentience extension: {extension_path}")

	profile = BrowserProfile(
		headless=False,
		args=[
			f"--load-extension={extension_path}",
			f"--disable-extensions-except={extension_path}",
		],
	)

	session = BrowserSession(browser_profile=profile)
	await session.start()

	try:
		# Navigate to a page with many elements
		page = await session.get_current_page()
		await page.goto("https://news.ycombinator.com")
		print("Navigated to Hacker News")
		await asyncio.sleep(2)

		# Create Sentience backend
		adapter = BrowserUseAdapter(session)
		backend = await adapter.create_backend()

		# Create cached snapshot with 2-second freshness
		cache = CachedSnapshot(backend, max_age_ms=2000)

		# Take initial snapshot (cached)
		snap1 = await cache.get()
		print(f"Initial snapshot: {len(snap1.elements)} elements")
		print(f"Cache age: {cache.age_ms:.0f}ms")

		# Second call uses cached version (no extension call)
		snap2 = await cache.get()
		print(f"Cached snapshot: {len(snap2.elements)} elements")
		print(f"Cache age: {cache.age_ms:.0f}ms")
		assert snap1 is snap2, "Should be same cached instance"

		# Find all links on the page
		links = query(snap1, "role=link")
		print(f"Found {len(links)} links on page")

		# Find the first story link (links with numeric index have class 'storylink' historically)
		story_links = [el for el in links if el.name and len(el.name) > 10]
		if story_links:
			print(f"\nFirst few story titles:")
			for link in story_links[:3]:
				print(f"  - {link.name[:50]}...")

		# Scroll down the page
		print("\nScrolling down...")
		await scroll(backend, delta_y=500)

		# After scroll, cache should still be valid (scroll doesn't change DOM)
		# But if we want fresh element positions, we force refresh
		cache.invalidate()  # Manual invalidation
		print("Cache invalidated after scroll")

		# Take fresh snapshot to get updated element positions
		snap3 = await cache.get()
		print(f"Fresh snapshot after scroll: {len(snap3.elements)} elements")
		print(f"Cache age: {cache.age_ms:.0f}ms")

		# Demonstrate force_refresh parameter
		snap4 = await cache.get(force_refresh=True)
		print(f"Force refresh: {len(snap4.elements)} elements")

		# Find the "More" link at bottom
		more_link = find(snap4, 'role=link[name="More"]')
		if more_link:
			print(f"\nFound 'More' link at: {more_link.bbox}")

			# Click to load next page
			await click(backend, more_link.bbox)
			print("Clicked 'More' link")

			# Invalidate cache after navigation
			cache.invalidate()

			# Wait for new content
			await asyncio.sleep(2)

			# Take snapshot of new page
			snap5 = await cache.get()
			print(f"New page snapshot: {len(snap5.elements)} elements")

		# Demo: Print cache statistics
		print("\n--- Cache Usage Pattern ---")
		print("1. Take initial snapshot: cache.get()")
		print("2. Reuse for multiple queries: find(snap, ...), query(snap, ...)")
		print("3. After DOM changes: cache.invalidate()")
		print("4. Get fresh data: cache.get()")

		print("\nPress Enter to close browser...")
		input()

	finally:
		await session.close()


if __name__ == "__main__":
	asyncio.run(main())
