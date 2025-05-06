import os
import shutil
import pytest
from patchright.async_api import async_playwright


@pytest.mark.asyncio
async def test_launch_with_user_binary():
	# In GitHub Actions, Chrome is usually available as 'google-chrome'
    chrome_path = shutil.which("google-chrome")

    if not chrome_path or not os.path.exists(chrome_path):
        pytest.skip("System Chrome binary not found")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=chrome_path,
            headless=True,
        )
        page = await browser.new_page()
        await page.goto("https://example.com")
        title = await page.title()
        assert "Example Domain" in title
        await browser.close()

if __name__ == '__main__':
	asyncio.run(test_launch_with_user_binary())
