"""
Example of how to use user_data_dir with a specific profile_directory.

This example will:
1. Launch a browser with a user_data_dir and a specific profile_directory
2. Navigate to a website and perform actions that will be saved to that profile
3. Close the browser
4. Relaunch with the same profile to maintain state

Usage:
    python examples/browser/profile_directory_example.py
"""

import asyncio
import os
import tempfile
from pathlib import Path

from browser_use.browser.browser import Browser, BrowserConfig


async def main():
    # Create a directory for the user data
    # In a real application, you would use a persistent directory
    user_data_dir = os.path.join(tempfile.gettempdir(), "browser_use_profiles")
    os.makedirs(user_data_dir, exist_ok=True)
    
    # Use "Profile 1" instead of "Default"
    profile_directory = "Profile 1"
    
    print(f"Using user data directory: {user_data_dir}")
    print(f"Using profile directory: {profile_directory}")

    # First browser session - visit a site and perform an action
    print("\n=== First browser session with Profile 1 ===")
    config = BrowserConfig(
        headless=False,
        user_data_dir=user_data_dir,
        profile_directory=profile_directory,
        browser_class="chromium"  # Must be chromium for profile_directory
    )
    browser = Browser(config=config)
    context = await browser.new_context()
    
    # Navigate to a site that will store some state
    page = await context.get_current_page()
    await page.goto("https://www.google.com")
    
    # Type something to demonstrate state persistence
    await page.fill('input[name="q"]', "browser-use Profile 1 example")
    
    print("Waiting 3 seconds before closing browser...")
    await asyncio.sleep(3)
    
    # Close the browser
    await browser.close()
    print("Browser closed. Session data should be saved to the specified profile.")
    
    # Wait a moment before launching again
    print("\nWaiting 2 seconds before starting second session...\n")
    await asyncio.sleep(2)
    
    # Second browser session - should maintain state from first session
    print("=== Second browser session with Profile 1 ===")
    print("Launching browser with the same profile...")
    
    config = BrowserConfig(
        headless=False,
        user_data_dir=user_data_dir,
        profile_directory=profile_directory,
        browser_class="chromium"
    )
    browser = Browser(config=config)
    context = await browser.new_context()
    
    # Navigate to the same site - should have our search preserved
    page = await context.get_current_page()
    await page.goto("https://www.google.com")
    
    # Notice that the search input should still have our previous text
    print("Check if the search input still contains our previous text")
    print("Waiting 5 seconds before closing browser...")
    await asyncio.sleep(5)
    
    # Close the browser
    await browser.close()
    print("Browser closed")


if __name__ == "__main__":
    asyncio.run(main()) 