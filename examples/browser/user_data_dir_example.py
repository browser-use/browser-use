"""
Example of how to use user_data_dir for browser persistence.

This example will:
1. Launch a browser with a user_data_dir
2. Navigate to a website
3. Close the browser
4. Relaunch the browser with the same user_data_dir to maintain state

Usage:
    python examples/browser/user_data_dir_example.py
"""

import asyncio
import os
import tempfile
from pathlib import Path

from browser_use.browser.browser import Browser, BrowserConfig


async def main():
    # Create a temporary directory for the user data
    # In a real application, you would use a persistent directory
    user_data_dir = os.path.join(tempfile.gettempdir(), "browser_use_data_dir")
    os.makedirs(user_data_dir, exist_ok=True)
    print(f"Using user data directory: {user_data_dir}")

    # First browser session - visit a site and perform an action
    print("\n=== First browser session ===")
    print("Initializing browser with user_data_dir (this may take a moment)...")
    config = BrowserConfig(
        headless=False,  # Make sure browser is visible
        browser_class="chromium",  # Explicitly use chromium for compatibility
        browser_instance_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        extra_browser_args=["--start-maximized"],  # Make the window visible and large
        user_data_dir=user_data_dir
    )
    browser = Browser(config=config)
    
    print("Creating browser context...")
    context = await browser.new_context()
    
    print("Getting current page...")
    # Navigate to a site that will store some state
    page = await context.get_current_page()
    
    print("Navigating to example.com...")
    await page.goto("https://example.com")
    
    print("Adding a note to localStorage to demonstrate persistence...")
    # Add something to localStorage to demonstrate state persistence
    await page.evaluate("""() => {
        localStorage.setItem('browser_use_test', 'This data should persist between sessions');
        document.body.style.backgroundColor = 'lightblue';
        const div = document.createElement('div');
        div.style.padding = '20px';
        div.style.fontSize = '24px';
        div.textContent = 'Session 1: Data saved to localStorage';
        document.body.appendChild(div);
    }""")
    
    print("Waiting 5 seconds to view the page...")
    await asyncio.sleep(5)
    
    # Close the browser
    print("Closing browser...")
    await browser.close()
    print("Browser closed. Session data should be saved to the user data directory.")
    
    # Wait a moment before launching again
    print("\nWaiting 2 seconds before starting second session...\n")
    await asyncio.sleep(2)
    
    # Second browser session - should maintain state from first session
    print("=== Second browser session ===")
    print("Launching browser with the same user data directory...")
    
    # Use the same config with browser_instance_path as the first session
    browser = Browser(config=config)
    
    print("Creating browser context...")
    context = await browser.new_context()
    
    print("Getting current page...")
    page = await context.get_current_page()
    
    print("Navigating to example.com again...")
    await page.goto("https://example.com")
    
    # Check if our data persisted
    print("Checking if localStorage data persisted...")
    stored_data = await page.evaluate("""() => {
        const data = localStorage.getItem('browser_use_test');
        document.body.style.backgroundColor = 'lightgreen';
        const div = document.createElement('div');
        div.style.padding = '20px';
        div.style.fontSize = '24px';
        div.textContent = 'Session 2: Retrieved from localStorage: ' + data;
        document.body.appendChild(div);
        return data;
    }""")
    
    print(f"Retrieved localStorage data: {stored_data}")
    print("Waiting 5 seconds to view the page...")
    await asyncio.sleep(5)
    
    # Close the browser
    print("Closing browser...")
    await browser.close()
    print("Browser closed - Test complete!")


if __name__ == "__main__":
    asyncio.run(main()) 