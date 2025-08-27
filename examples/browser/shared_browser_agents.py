"""
# @file purpose: Demonstrates how multiple agents can share the same browser session via CDP
This example shows how to:
1. Set up a shared browser session using CDP
2. Have multiple agents work sequentially in the same browser
3. Share browser state and tabs between agents
4. Access the shared browser session from custom controller actions

This is useful for workflows where you want multiple specialized agents to work 
together in the same browser context, sharing cookies, sessions, and navigation state.
"""

import asyncio
import logging
import os
import sys
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, Controller, ActionResult
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI
from playwright.async_api import Page

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SharedBrowserController(Controller):
    """Custom controller that can access and manipulate the shared browser session."""
    
    def __init__(self):
        super().__init__()
        
        @self.action("Get current browser tabs and their information")
        async def get_browser_tabs_info(browser_session: BrowserSession) -> ActionResult:
            """Get information about all open tabs in the shared browser."""
            try:
                tabs = await browser_session.get_tabs()
                tab_info = []
                
                for tab in tabs:
                    tab_info.append({
                        'id': tab.get('targetId', 'unknown'),
                        'url': tab.get('url', 'unknown'),
                        'title': tab.get('title', 'unknown'),
                        'type': tab.get('type', 'unknown')
                    })
                
                result = f"Found {len(tab_info)} tabs:\n"
                for i, tab in enumerate(tab_info, 1):
                    result += f"{i}. {tab['title']} - {tab['url']}\n"
                
                return ActionResult(
                    extracted_content=result,
                    include_in_memory=True
                )
            except Exception as e:
                return ActionResult(
                    error=f"Failed to get tab information: {str(e)}",
                    include_in_memory=True
                )
        
        @self.action("Switch to a specific tab by index (1-based)")
        async def switch_to_tab_by_index(tab_index: int, browser_session: BrowserSession) -> ActionResult:
            """Switch to a specific tab by its index (1-based numbering)."""
            try:
                tabs = await browser_session.get_tabs()
                
                if tab_index < 1 or tab_index > len(tabs):
                    return ActionResult(
                        error=f"Invalid tab index {tab_index}. Available tabs: 1-{len(tabs)}",
                        include_in_memory=True
                    )
                
                target_tab = tabs[tab_index - 1]
                target_id = target_tab.get('targetId')
                
                if target_id:
                    await browser_session.switch_to_tab(target_id)
                    return ActionResult(
                        extracted_content=f"Switched to tab {tab_index}: {target_tab.get('title', 'Unknown')}",
                        include_in_memory=True
                    )
                else:
                    return ActionResult(
                        error=f"Could not find target ID for tab {tab_index}",
                        include_in_memory=True
                    )
                    
            except Exception as e:
                return ActionResult(
                    error=f"Failed to switch to tab {tab_index}: {str(e)}",
                    include_in_memory=True
                )

        @self.action("Create a new tab and navigate to URL")
        async def create_new_tab(url: str, browser_session: BrowserSession) -> ActionResult:
            """Create a new tab and navigate to the specified URL."""
            try:
                # Create new tab
                new_tab = await browser_session.create_tab()
                target_id = new_tab.get('targetId')
                
                if target_id:
                    # Switch to the new tab
                    await browser_session.switch_to_tab(target_id)
                    # Navigate to the URL
                    await browser_session.navigate_to(url)
                    
                    return ActionResult(
                        extracted_content=f"Created new tab and navigated to: {url}",
                        include_in_memory=True
                    )
                else:
                    return ActionResult(
                        error="Failed to create new tab - no target ID returned",
                        include_in_memory=True
                    )
                    
            except Exception as e:
                return ActionResult(
                    error=f"Failed to create new tab: {str(e)}",
                    include_in_memory=True
                )


async def setup_shared_browser() -> BrowserSession:
    """Set up a shared browser session that multiple agents can connect to."""
    logger.info("🚀 Setting up shared browser session...")
    
    # Create a browser session with keep_alive=True so it persists between agents
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            headless=False,  # Show browser window so you can see what's happening
            keep_alive=True,  # Important: keeps browser alive between agent runs
            user_data_dir='~/.config/browseruse/profiles/shared_demo',  # Shared profile
        )
    )
    
    # Start the browser session
    await browser_session.start()
    logger.info(f"✅ Browser session started with CDP URL: {browser_session.cdp_url}")
    
    return browser_session


async def create_agent_with_shared_browser(
    task: str, 
    browser_session: BrowserSession,
    agent_name: str,
    use_custom_controller: bool = False
) -> Agent:
    """Create an agent that connects to the shared browser session."""
    
    controller = SharedBrowserController() if use_custom_controller else Controller()
    
    # Create agent with the shared browser session
    agent = Agent(
        task=task,
        llm=ChatOpenAI(model='gpt-4o-mini'),
        browser=browser_session,  # Use the shared browser session
        controller=controller,
    )
    
    logger.info(f"🤖 Created agent '{agent_name}' with task: {task}")
    return agent


async def demonstrate_shared_browser_workflow():
    """Demonstrate a workflow where multiple agents work in the same browser."""
    
    # Set up the shared browser session
    shared_browser = await setup_shared_browser()
    
    try:
        # Agent 1: Research agent - opens multiple tabs for research
        logger.info("\n" + "="*60)
        logger.info("🔍 AGENT 1 (Research): Opening research tabs")
        logger.info("="*60)
        
        research_agent = await create_agent_with_shared_browser(
            task="Open 3 different tabs: 1) Go to https://github.com/browser-use/browser-use, "
                 "2) Create a new tab and go to https://docs.browser-use.com, "
                 "3) Create another tab and go to https://python.org. "
                 "Leave all tabs open for the next agent.",
            browser_session=shared_browser,
            agent_name="Research Agent"
        )
        
        await research_agent.run()
        
        # Small pause to see the results
        await asyncio.sleep(2)
        
        # Agent 2: Analysis agent - uses custom controller to analyze tabs
        logger.info("\n" + "="*60)
        logger.info("📊 AGENT 2 (Analysis): Analyzing open tabs using custom controller")
        logger.info("="*60)
        
        analysis_agent = await create_agent_with_shared_browser(
            task="Use the get_browser_tabs_info action to see what tabs are open, "
                 "then visit each tab and summarize what you find. "
                 "Use the switch_to_tab_by_index action to navigate between tabs.",
            browser_session=shared_browser,
            agent_name="Analysis Agent",
            use_custom_controller=True
        )
        
        await analysis_agent.run()
        
        # Small pause to see the results
        await asyncio.sleep(2)
        
        # Agent 3: Action agent - performs specific actions
        logger.info("\n" + "="*60)
        logger.info("⚡ AGENT 3 (Action): Performing specific actions")
        logger.info("="*60)
        
        action_agent = await create_agent_with_shared_browser(
            task="Go to the GitHub tab (browser-use repository), star the repository if not already starred, "
                 "then create a new tab and search for 'browser automation python' on Google.",
            browser_session=shared_browser,
            agent_name="Action Agent",
            use_custom_controller=True
        )
        
        await action_agent.run()
        
        logger.info("\n" + "="*60)
        logger.info("✅ WORKFLOW COMPLETE")
        logger.info("="*60)
        logger.info("All agents have completed their tasks in the shared browser!")
        logger.info("The browser window will remain open so you can see the final state.")
        
        # Keep the browser open for inspection
        input("\nPress Enter to close the browser and exit...")
        
    finally:
        # Clean up the shared browser session
        logger.info("🧹 Cleaning up shared browser session...")
        await shared_browser.kill()


async def demonstrate_concurrent_agents():
    """Demonstrate multiple agents working in the same browser concurrently (different tabs)."""
    
    logger.info("\n" + "="*80)
    logger.info("🔄 CONCURRENT AGENTS DEMO: Multiple agents working simultaneously")
    logger.info("="*80)
    
    # Set up the shared browser session
    shared_browser = await setup_shared_browser()
    
    try:
        # Create multiple agents that will work concurrently
        agents_tasks = [
            (
                "Open a new tab, go to https://news.ycombinator.com and summarize the top 3 stories",
                "News Agent"
            ),
            (
                "Open a new tab, go to https://stackoverflow.com and find questions about Python automation",
                "Tech Agent"
            ),
            (
                "Open a new tab, go to https://github.com/trending/python and list the top 3 trending Python repositories",
                "Trending Agent"
            )
        ]
        
        # Create agents
        agents = []
        for task, name in agents_tasks:
            agent = await create_agent_with_shared_browser(
                task=task,
                browser_session=shared_browser,
                agent_name=name,
                use_custom_controller=True
            )
            agents.append(agent)
        
        # Run agents concurrently (they'll work in different tabs)
        logger.info("🚀 Running agents concurrently...")
        await asyncio.gather(*[agent.run() for agent in agents])
        
        logger.info("\n" + "="*60)
        logger.info("✅ CONCURRENT WORKFLOW COMPLETE")
        logger.info("="*60)
        logger.info("All agents completed their tasks concurrently!")
        
        # Keep the browser open for inspection
        input("\nPress Enter to close the browser and exit...")
        
    finally:
        # Clean up the shared browser session
        logger.info("🧹 Cleaning up shared browser session...")
        await shared_browser.kill()


async def main():
    """Main function to run the shared browser demonstrations."""
    
    print("Browser-Use Shared Browser Demo")
    print("=" * 40)
    print("This demo shows how multiple agents can share the same browser session.")
    print()
    print("Choose a demo to run:")
    print("1. Sequential agents (recommended for beginners)")
    print("2. Concurrent agents (advanced)")
    print()
    
    while True:
        choice = input("Enter your choice (1 or 2): ").strip()
        if choice == "1":
            await demonstrate_shared_browser_workflow()
            break
        elif choice == "2":
            await demonstrate_concurrent_agents()
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