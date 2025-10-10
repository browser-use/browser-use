import asyncio
import logging
import os
from browser_use import Browser

# ✅ Configure Python logging manually (no setup_logger)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s [%(name)s] %(message)s"
)

DOWNLOAD_DIR = "/tmp/browser-use-downloads-test"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

async def run_test():
    print(f"✅ Starting Browser Use download path test")
    print(f"📁 Download directory: {DOWNLOAD_DIR}")

    # Configure Browser with explicit downloads path
    browser = await Browser.create(
        headless=True,
        downloads_path=DOWNLOAD_DIR,
        record_video_dir=None,
    )

    try:
        page = await browser.new_page()

        print("🌐 Navigating to file generation site...")
        await page.goto("https://file-examples.com/index.php/sample-documents-download/")
        await page.wait_for_timeout(3000)

        print("📄 Attempting to click a sample file download link...")
        await page.click("a[href*='file_example_DOC_50kB.doc']")
        await page.wait_for_timeout(5000)

        print("🔍 Checking downloaded files in:", DOWNLOAD_DIR)
        files = os.listdir(DOWNLOAD_DIR)
        if files:
            print("✅ Files found:", files)
        else:
            print("❌ No files found. Downloads not saved in this pod (likely in CDP pod).")

    except Exception as e:
        print("❌ Error during test:", e)

    finally:
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_test())
