from browser_use import Agent, BrowserProfile, ChatBrowserUse
from dotenv import load_dotenv
import asyncio
import glob
from pathlib import Path

# Sentience SDK imports
from sentience import get_extension_dir

load_dotenv()

async def main():
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
                print(f"✅ Found Playwright browser: {executable_path}")
                break
    
    if not executable_path:
        print("⚠️  Playwright browser not found, browser-use will try to install it")
    
    # Get Sentience extension path
    sentience_ext_path = get_extension_dir()
    print(f"Loading Sentience extension from: {sentience_ext_path}")
    
    # Get default extension paths and combine with Sentience extension
    # Chrome only uses the LAST --load-extension arg, so we must combine all extensions
    all_extension_paths = [sentience_ext_path]
    
    # Create a temporary profile to ensure default extensions are downloaded
    temp_profile = BrowserProfile(enable_default_extensions=True)
    default_ext_paths = temp_profile._ensure_default_extensions_downloaded()
    
    if default_ext_paths:
        all_extension_paths.extend(default_ext_paths)
        print(f"Found {len(default_ext_paths)} default extensions")
    
    # Combine all extensions into a single --load-extension arg
    combined_extensions = ",".join(all_extension_paths)
    print(f"Loading {len(all_extension_paths)} extensions total (including Sentience)")
    
    # Create browser profile with ALL extensions combined
    browser_profile = BrowserProfile(
        executable_path=executable_path,  # Use Playwright browser if found
        enable_default_extensions=False,  # Disable auto-loading, we'll load manually
        args=[
            "--enable-extensions",
            "--disable-extensions-file-access-check",
            "--disable-extensions-http-throttling",
            "--extensions-on-chrome-urls",
            f"--load-extension={combined_extensions}",  # Load ALL extensions together
        ],
    )
    
    # Create agent with Sentience-enabled browser
    llm = ChatBrowserUse()
    task = "Find the number 1 post on Show HN"
    agent = Agent(
        task=task,
        llm=llm,
        browser_profile=browser_profile,
        calculate_cost=True
    )
    history = await agent.run()
    print(f"Token usage: {history.usage}")
    usage_summary = await agent.token_cost_service.get_usage_summary()
    print(f"Usage summary: {usage_summary}")

if __name__ == "__main__":
    asyncio.run(main())
