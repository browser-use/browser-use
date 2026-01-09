"""
Basic example: Sentience extension with browser-use.

This example demonstrates:
1. Loading the Sentience Chrome extension in browser-use
2. Taking a snapshot to detect page elements
3. Using semantic queries to find elements
4. Clicking on elements using grounded coordinates

Requirements:
    pip install browser-use sentienceapi

Usage:
    python playground/sentience_basic.py
"""

import asyncio
import glob
import logging
import os
import sys
from pathlib import Path

# Enable debug logging for sentience
logging.basicConfig(level=logging.DEBUG, format='%(name)s - %(levelname)s - %(message)s')

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from browser_use.browser import BrowserProfile, BrowserSession

# Sentience SDK imports
from sentience import find, get_extension_dir, query
from sentience.backends import (
	BrowserUseAdapter,
	ExtensionNotLoadedError,
	click,
	snapshot,
	type_text,
)


def log(msg: str) -> None:
	"""Print with flush for immediate output."""
	print(msg, flush=True)


async def main():
	"""Demo: Use Sentience grounding with browser-use to search Google."""

	# Get path to Sentience extension
	sentience_ext_path = get_extension_dir()
	log(f"Loading Sentience extension from: {sentience_ext_path}")
	
	# Verify extension exists
	if not os.path.exists(sentience_ext_path):
		raise FileNotFoundError(f"Sentience extension not found at: {sentience_ext_path}")
	if not os.path.exists(os.path.join(sentience_ext_path, "manifest.json")):
		raise FileNotFoundError(f"Sentience extension manifest not found at: {sentience_ext_path}/manifest.json")
	log(f"✅ Sentience extension verified at: {sentience_ext_path}")

	# Find Playwright browser to avoid password prompt
	playwright_path = Path.home() / "Library/Caches/ms-playwright"
	chromium_patterns = [
		playwright_path / "chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
		playwright_path / "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
	]
	
	executable_path = None
	for pattern in chromium_patterns:
		matches = glob.glob(str(pattern))
		if matches:
			matches.sort()
			executable_path = matches[-1]  # Use latest version
			if Path(executable_path).exists():
				log(f"✅ Found Playwright browser: {executable_path}")
				break
	
	if not executable_path:
		log("⚠️  Playwright browser not found, browser-use will try to install it")

	# Get default extension paths and combine with Sentience extension
	# Chrome only uses the LAST --load-extension arg, so we must combine all extensions
	log("Collecting all extension paths...")
	all_extension_paths = [sentience_ext_path]
	
	# Create a temporary profile to ensure default extensions are downloaded
	# This ensures extensions exist before we try to load them
	temp_profile = BrowserProfile(enable_default_extensions=True)
	default_ext_paths = temp_profile._ensure_default_extensions_downloaded()
	
	if default_ext_paths:
		all_extension_paths.extend(default_ext_paths)
		log(f"  ✅ Found {len(default_ext_paths)} default extensions")
	else:
		log("  ⚠️  No default extensions found (this is OK, Sentience will still work)")
	
	log(f"Total extensions to load: {len(all_extension_paths)} (including Sentience)")
	
	# Combine all extensions into a single --load-extension arg
	combined_extensions = ",".join(all_extension_paths)
	log(f"Combined extension paths (first 100 chars): {combined_extensions[:100]}...")

	# Create browser profile with ALL extensions combined
	# Strategy: Disable default extensions, manually load all together
	profile = BrowserProfile(
		headless=False,  # Run with visible browser for demo
		executable_path=executable_path,  # Use Playwright browser if found
		enable_default_extensions=False,  # Disable auto-loading, we'll load manually
		ignore_default_args=[
			"--enable-automation",
			"--disable-extensions",  # Important: don't disable extensions
			"--hide-scrollbars",
			# Don't disable component extensions - we need background pages for Sentience
		],
		args=[
			"--enable-extensions",
			"--disable-extensions-file-access-check",  # Allow extension file access
			"--disable-extensions-http-throttling",  # Don't throttle extension HTTP
			"--extensions-on-chrome-urls",  # Allow extensions on chrome:// URLs
			f"--load-extension={combined_extensions}",  # Load ALL extensions together
		],
	)
	
	log("Browser profile configured with Sentience extension")

	# Start browser session
	log("Creating BrowserSession...")
	session = BrowserSession(browser_profile=profile)
	log("Starting browser session (this may take a moment)...")
	try:
		await session.start()
		log("✅ Browser session started successfully")
	except Exception as e:
		log(f"❌ Error starting browser session: {e}")
		import traceback
		log(traceback.format_exc())
		return

	try:
		# Navigate to Google
		log("Getting current page...")
		try:
			page = await session.get_current_page()
			log(f"✅ Got page: {page}")
		except Exception as e:
			log(f"❌ Error getting page: {e}")
			import traceback
			log(traceback.format_exc())
			return
		
		log("Navigating to Google...")
		try:
			await page.goto("https://www.google.com")
			log("✅ Navigated to Google")
		except Exception as e:
			log(f"❌ Error navigating to Google: {e}")
			import traceback
			log(traceback.format_exc())
			return

		# Wait for page to settle
		log("Waiting 2 seconds for page to settle...")
		await asyncio.sleep(2)
		log("Done waiting")

		# Create Sentience adapter and backend
		log("Creating Sentience adapter...")
		adapter = BrowserUseAdapter(session)
		log("Creating backend...")
		backend = await adapter.create_backend()
		log("Created Sentience backend")
		
		# Give extension more time to initialize after page load
		log("Waiting for extension to initialize...")
		await asyncio.sleep(1)

		# Take a snapshot using Sentience extension
		try:
			log("Taking snapshot (this waits for extension to inject)...")
			
			# Enhanced diagnostics before snapshot
			log("Checking extension injection status...")
			diag = await backend.eval("""
				(() => {
					const hasSentience = typeof window.sentience !== 'undefined';
					const hasSnapshot = hasSentience && typeof window.sentience.snapshot === 'function';
					const extId = document.documentElement.dataset.sentienceExtensionId || null;
					return {
						window_sentience: hasSentience,
						window_sentience_snapshot: hasSnapshot,
						extension_id_attr: extId,
						url: window.location.href,
						ready_state: document.readyState
					};
				})()
			""")
			log(f"Extension diagnostics: {diag}")
			
			if not diag.get("window_sentience"):
				log("⚠️  window.sentience not found - extension may not have injected yet")
				log("   This can happen if:")
				log("   1. Extension wasn't loaded in browser args")
				log("   2. Page loaded before extension could inject")
				log("   3. Content Security Policy is blocking the extension")
				log("   Waiting for extension injection (up to 10 seconds)...")
			else:
				log("✅ window.sentience found!")

			snap = await snapshot(backend)
			log(f"✅ Snapshot taken: {len(snap.elements)} elements found")
		except ExtensionNotLoadedError as e:
			log(f"❌ Extension not loaded error:")
			log(f"   {e}")
			if hasattr(e, 'diagnostics') and e.diagnostics:
				log(f"   Diagnostics: {e.diagnostics.to_dict()}")
			log("\nTroubleshooting steps:")
			log("1. Verify extension path exists and contains manifest.json")
			log(f"2. Check browser console for extension errors")
			log("3. Try increasing timeout in snapshot() call")
			log("4. Ensure --enable-extensions is in browser args")
			return

		# Find the search input using semantic query
		# Google's search box has role=combobox or role=textbox
		search_input = find(snap, 'role=combobox[name*="Search"]')
		if not search_input:
			search_input = find(snap, 'role=textbox[name*="Search"]')

		if search_input:
			print(f"Found search input: {search_input.role} at {search_input.bbox}")

			# Click on the search input using grounded coordinates
			await click(backend, search_input.bbox)
			print("Clicked on search input")

			# Type a search query
			await type_text(backend, "Sentience AI browser automation")
			print("Typed search query")

			# Take another snapshot after typing
			await asyncio.sleep(1)
			snap2 = await snapshot(backend)
			print(f"After typing: {len(snap2.elements)} elements")

			# Find and click the search button
			search_btn = find(snap2, 'role=button[name*="Search"]')
			if search_btn:
				await click(backend, search_btn.bbox)
				print("Clicked search button")
		else:
			print("Could not find search input")
			# List all textbox/combobox elements for debugging
			textboxes = query(snap, "role=textbox")
			comboboxes = query(snap, "role=combobox")
			print(f"Found {len(textboxes)} textboxes, {len(comboboxes)} comboboxes")

		# Keep browser open for inspection
		print("\nPress Enter to close browser...")
		input()

	finally:
		await session.close()


if __name__ == "__main__":
	asyncio.run(main())
