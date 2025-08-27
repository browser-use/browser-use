"""
# @file purpose: Demonstrates connecting multiple agents to an existing browser via CDP websocket
This example shows how to:
1. Connect to an existing browser instance running with remote debugging
2. Have multiple agents connect to the same browser via its CDP endpoint
3. Work with an already-running browser process (like one started manually)

Prerequisites:
- Start Chrome/Chromium with remote debugging enabled:
  Chrome: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome --remote-debugging-port=9222
  Linux: google-chrome --remote-debugging-port=9222
  Windows: "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222

This approach is useful when:
- You want to connect to a browser that's already running
- You want to work with a browser that has existing sessions/logins
- You need to connect from multiple processes/scripts to the same browser
"""

import asyncio
import logging
import os
import sys
import json
from typing import Dict, List

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
import httpx

load_dotenv()

from browser_use import Agent, Controller, ActionResult
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ExistingBrowserController(Controller):
    """Controller with actions specifically for working with existing browsers."""
    
    def __init__(self):
        super().__init__()
        
        @self.action("List all available browser targets (tabs, pages, etc.)")
        async def list_browser_targets(browser_session: BrowserSession) -> ActionResult:
            """Get information about all available targets in the browser."""
            try:
                # Use CDP to get all targets
                targets_result = await browser_session.cdp_client.send.Target.getTargets()
                targets = targets_result.get('targetInfos', [])
                
                target_info = []
                for target in targets:
                    target_info.append({
                        'id': target.get('targetId', 'unknown'),
                        'type': target.get('type', 'unknown'),
                        'url': target.get('url', 'unknown'),
                        'title': target.get('title', 'unknown'),
                        'attached': target.get('attached', False)
                    })
                
                result = f"Found {len(target_info)} targets:\n"
                for i, target in enumerate(target_info, 1):
                    result += f"{i}. [{target['type']}] {target['title']} - {target['url']}\n"
                    result += f"   ID: {target['id'][:8]}... | Attached: {target['attached']}\n"
                
                return ActionResult(
                    extracted_content=result,
                    include_in_memory=True
                )
            except Exception as e:
                return ActionResult(
                    error=f"Failed to list targets: {str(e)}",
                    include_in_memory=True
                )
        
        @self.action("Get browser version and debugging info")
        async def get_browser_info(browser_session: BrowserSession) -> ActionResult:
            """Get information about the connected browser."""
            try:
                # Get version info
                version_result = await browser_session.cdp_client.send.Browser.getVersion()
                
                info = f"Browser Information:\n"
                info += f"Product: {version_result.get('product', 'Unknown')}\n"
                info += f"Version: {version_result.get('revision', 'Unknown')}\n"
                info += f"User Agent: {version_result.get('userAgent', 'Unknown')}\n"
                info += f"V8 Version: {version_result.get('jsVersion', 'Unknown')}\n"
                
                return ActionResult(
                    extracted_content=info,
                    include_in_memory=True
                )
            except Exception as e:
                return ActionResult(
                    error=f"Failed to get browser info: {str(e)}",
                    include_in_memory=True
                )


async def check_browser_availability(port: int = 9222) -> Dict:
    """Check if a browser with remote debugging is available."""
    try:
        async with httpx.AsyncClient() as client:
            # Try to get version info
            response = await client.get(f"http://localhost:{port}/json/version")
            if response.status_code == 200:
                version_info = response.json()
                logger.info(f"✅ Found browser: {version_info.get('Browser', 'Unknown')}")
                return version_info
            else:
                raise httpx.HTTPError(f"HTTP {response.status_code}")
    except Exception as e:
        logger.error(f"❌ No browser found on port {port}: {e}")
        logger.error(f"Please start Chrome with: --remote-debugging-port={port}")
        return {}


async def get_browser_tabs(port: int = 9222) -> List[Dict]:
    """Get list of available tabs/pages in the browser."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://localhost:{port}/json")
            if response.status_code == 200:
                tabs = response.json()
                logger.info(f"Found {len(tabs)} tabs/pages in browser")
                return tabs
            else:
                raise httpx.HTTPError(f"HTTP {response.status_code}")
    except Exception as e:
        logger.error(f"Failed to get browser tabs: {e}")
        return []


async def connect_to_existing_browser(cdp_url: str) -> BrowserSession:
    """Connect to an existing browser via its CDP URL."""
    logger.info(f"🔌 Connecting to existing browser at: {cdp_url}")
    
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            cdp_url=cdp_url,
            is_local=False,  # We're connecting to existing browser
            keep_alive=True,  # Don't close the browser when agent finishes
        )
    )
    
    # Connect to the existing browser
    await browser_session.start()
    logger.info("✅ Successfully connected to existing browser")
    
    return browser_session


async def demonstrate_multiple_agents_existing_browser():
    """Demonstrate multiple agents connecting to the same existing browser."""
    
    port = 9222
    
    # Check if browser is available
    logger.info("🔍 Checking for existing browser...")
    browser_info = await check_browser_availability(port)
    if not browser_info:
        print("\n❌ No browser found!")
        print("Please start Chrome with remote debugging enabled:")
        print(f"  Chrome --remote-debugging-port={port}")
        print("Then visit http://localhost:9222 to verify it's working")
        return
    
    # Get WebSocket debugging URL
    websocket_url = browser_info.get('webSocketDebuggerUrl')
    if not websocket_url:
        logger.error("❌ No WebSocket debugger URL found")
        return
    
    # Show available tabs
    tabs = await get_browser_tabs(port)
    if tabs:
        print(f"\n📑 Found {len(tabs)} tabs in the browser:")
        for i, tab in enumerate(tabs[:5], 1):  # Show first 5 tabs
            print(f"  {i}. {tab.get('title', 'Untitled')} - {tab.get('url', 'No URL')}")
        if len(tabs) > 5:
            print(f"  ... and {len(tabs) - 5} more tabs")
    
    print(f"\n🚀 Connecting agents to existing browser...")
    
    try:
        # Connect to the existing browser
        shared_browser = await connect_to_existing_browser(websocket_url)
        
        # Agent 1: Inspector - analyzes the current browser state
        logger.info("\n" + "="*60)
        logger.info("🕵️ AGENT 1 (Inspector): Analyzing existing browser state")
        logger.info("="*60)
        
        inspector_agent = Agent(
            task="Use the list_browser_targets and get_browser_info actions to analyze "
                 "the current state of this browser. Tell me what tabs are open and "
                 "what browser version is running.",
            llm=ChatOpenAI(model='gpt-4o-mini'),
            browser=shared_browser,
            controller=ExistingBrowserController(),
        )
        
        await inspector_agent.run()
        
        # Agent 2: Navigator - works with existing tabs
        logger.info("\n" + "="*60)
        logger.info("🧭 AGENT 2 (Navigator): Working with existing content")
        logger.info("="*60)
        
        navigator_agent = Agent(
            task="Look at the tabs that are currently open. If there are any interesting "
                 "websites open, summarize their content. If not, open a new tab and "
                 "go to https://github.com/browser-use/browser-use to learn about browser-use.",
            llm=ChatOpenAI(model='gpt-4o-mini'),
            browser=shared_browser,
            controller=ExistingBrowserController(),
        )
        
        await navigator_agent.run()
        
        # Agent 3: Researcher - adds new content
        logger.info("\n" + "="*60)
        logger.info("🔬 AGENT 3 (Researcher): Adding research content")
        logger.info("="*60)
        
        researcher_agent = Agent(
            task="Open a new tab and research 'Python web automation' on Google. "
                 "Find and summarize information about the top 3 Python libraries "
                 "for web automation.",
            llm=ChatOpenAI(model='gpt-4o-mini'),
            browser=shared_browser,
            controller=ExistingBrowserController(),
        )
        
        await researcher_agent.run()
        
        logger.info("\n" + "="*60)
        logger.info("✅ ALL AGENTS COMPLETED")
        logger.info("="*60)
        logger.info("All agents have finished working with the existing browser.")
        logger.info("The browser will remain open since it was already running.")
        
    except Exception as e:
        logger.error(f"❌ Error during demonstration: {e}")
        raise


async def demonstrate_connecting_via_cdp_url():
    """Demonstrate connecting to browser using different CDP URL formats."""
    
    port = 9222
    
    print("🔗 Browser-Use CDP Connection Demo")
    print("=" * 50)
    print("This demo shows different ways to connect to an existing browser:")
    print()
    
    # Check browser availability
    browser_info = await check_browser_availability(port)
    if not browser_info:
        print("❌ No browser found. Please start Chrome with:")
        print(f"   Chrome --remote-debugging-port={port}")
        return
    
    websocket_url = browser_info.get('webSocketDebuggerUrl')
    http_url = f"http://localhost:{port}"
    
    print(f"✅ Browser detected!")
    print(f"   HTTP endpoint: {http_url}")
    print(f"   WebSocket URL: {websocket_url}")
    print()
    
    # Demonstrate different connection methods
    connection_methods = [
        ("HTTP URL", http_url),
        ("WebSocket URL", websocket_url),
    ]
    
    for method_name, url in connection_methods:
        print(f"🔌 Testing connection via {method_name}: {url}")
        
        try:
            # Create browser session with the URL
            browser_session = BrowserSession(
                browser_profile=BrowserProfile(
                    cdp_url=url,
                    is_local=False,
                    keep_alive=True,
                )
            )
            
            # Connect and test
            await browser_session.start()
            
            # Create a simple agent to test the connection
            test_agent = Agent(
                task="You are connected to an existing browser. Simply navigate to "
                     "https://httpbin.org/user-agent and tell me what user agent is displayed.",
                llm=ChatOpenAI(model='gpt-4o-mini'),
                browser=browser_session,
            )
            
            await test_agent.run()
            
            print(f"✅ {method_name} connection successful!")
            
            # Don't close the browser session since we're just testing
            
        except Exception as e:
            print(f"❌ {method_name} connection failed: {e}")
        
        print()


async def main():
    """Main function to run the existing browser connection demos."""
    
    print("Browser-Use Existing Browser Connection Demo")
    print("=" * 50)
    print("This demo shows how to connect to an existing browser instance.")
    print()
    print("Choose a demo to run:")
    print("1. Multiple agents with existing browser (recommended)")
    print("2. Test different CDP connection methods")
    print()
    
    while True:
        choice = input("Enter your choice (1 or 2): ").strip()
        if choice == "1":
            await demonstrate_multiple_agents_existing_browser()
            break
        elif choice == "2":
            await demonstrate_connecting_via_cdp_url()
            break
        else:
            print("Invalid choice. Please enter 1 or 2.")


if __name__ == '__main__':
    # Make sure OpenAI API key is set
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ Please set your OPENAI_API_KEY environment variable")
        print("You can do this by creating a .env file with: OPENAI_API_KEY=your_key_here")
        sys.exit(1)
    
    asyncio.run(main())