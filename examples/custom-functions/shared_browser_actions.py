"""
# @file purpose: Demonstrates custom controller actions for shared browser session management
This example shows how to create custom controller actions that can:
1. Access the shared browser session from within actions
2. Manipulate browser state (tabs, windows, etc.) across agents
3. Share data between agents through browser storage or state
4. Coordinate agent workflows using browser-based communication

This is useful for:
- Building complex multi-agent workflows
- Creating specialized browser automation tools
- Implementing agent-to-agent communication via browser state
- Building browser-based orchestration systems
"""

import asyncio
import json
import logging
import os
import sys
from typing import Dict, Any, List, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from browser_use import Agent, Controller, ActionResult
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.llm import ChatOpenAI
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BrowserStateManager(Controller):
    """Advanced controller with actions for managing shared browser state."""
    
    def __init__(self):
        super().__init__()
        self._setup_browser_actions()
    
    def _setup_browser_actions(self):
        """Set up all browser management actions."""
        
        @self.action("Store data in browser's localStorage for other agents to access")
        async def store_shared_data(
            key: str, 
            value: str, 
            browser_session: BrowserSession
        ) -> ActionResult:
            """Store data in localStorage that can be accessed by other agents."""
            try:
                # Use CDP to execute JavaScript that stores data in localStorage
                js_code = f"localStorage.setItem('{key}', '{value}');"
                
                if browser_session.current_target_id:
                    await browser_session.cdp_client.send.Runtime.evaluate(
                        expression=js_code,
                        targetId=browser_session.current_target_id
                    )
                    
                    return ActionResult(
                        extracted_content=f"Successfully stored data with key '{key}' in browser localStorage",
                        include_in_memory=True
                    )
                else:
                    return ActionResult(
                        error="No active tab to store data in",
                        include_in_memory=True
                    )
                    
            except Exception as e:
                return ActionResult(
                    error=f"Failed to store shared data: {str(e)}",
                    include_in_memory=True
                )
        
        @self.action("Retrieve data from browser's localStorage that was stored by other agents")
        async def get_shared_data(
            key: str, 
            browser_session: BrowserSession
        ) -> ActionResult:
            """Retrieve data from localStorage that was stored by other agents."""
            try:
                # Use CDP to execute JavaScript that retrieves data from localStorage
                js_code = f"localStorage.getItem('{key}');"
                
                if browser_session.current_target_id:
                    result = await browser_session.cdp_client.send.Runtime.evaluate(
                        expression=js_code,
                        targetId=browser_session.current_target_id,
                        returnByValue=True
                    )
                    
                    value = result.get('result', {}).get('value')
                    
                    if value is not None:
                        return ActionResult(
                            extracted_content=f"Retrieved data for key '{key}': {value}",
                            include_in_memory=True
                        )
                    else:
                        return ActionResult(
                            extracted_content=f"No data found for key '{key}'",
                            include_in_memory=True
                        )
                else:
                    return ActionResult(
                        error="No active tab to retrieve data from",
                        include_in_memory=True
                    )
                    
            except Exception as e:
                return ActionResult(
                    error=f"Failed to retrieve shared data: {str(e)}",
                    include_in_memory=True
                )
        
        @self.action("List all stored data keys in browser's localStorage")
        async def list_shared_data_keys(browser_session: BrowserSession) -> ActionResult:
            """List all available data keys in localStorage."""
            try:
                # JavaScript to get all localStorage keys
                js_code = "Object.keys(localStorage);"
                
                if browser_session.current_target_id:
                    result = await browser_session.cdp_client.send.Runtime.evaluate(
                        expression=js_code,
                        targetId=browser_session.current_target_id,
                        returnByValue=True
                    )
                    
                    keys = result.get('result', {}).get('value', [])
                    
                    if keys:
                        key_list = ", ".join(keys)
                        return ActionResult(
                            extracted_content=f"Available localStorage keys: {key_list}",
                            include_in_memory=True
                        )
                    else:
                        return ActionResult(
                            extracted_content="No data stored in localStorage",
                            include_in_memory=True
                        )
                else:
                    return ActionResult(
                        error="No active tab to check localStorage",
                        include_in_memory=True
                    )
                    
            except Exception as e:
                return ActionResult(
                    error=f"Failed to list localStorage keys: {str(e)}",
                    include_in_memory=True
                )
        
        @self.action("Set browser window title to communicate status to other agents")
        async def set_window_title(
            title: str, 
            browser_session: BrowserSession
        ) -> ActionResult:
            """Set the browser window title to communicate status."""
            try:
                # JavaScript to set document title
                js_code = f"document.title = '{title}';"
                
                if browser_session.current_target_id:
                    await browser_session.cdp_client.send.Runtime.evaluate(
                        expression=js_code,
                        targetId=browser_session.current_target_id
                    )
                    
                    return ActionResult(
                        extracted_content=f"Set window title to: {title}",
                        include_in_memory=True
                    )
                else:
                    return ActionResult(
                        error="No active tab to set title",
                        include_in_memory=True
                    )
                    
            except Exception as e:
                return ActionResult(
                    error=f"Failed to set window title: {str(e)}",
                    include_in_memory=True
                )
        
        @self.action("Create a coordination tab for agent communication")
        async def create_coordination_tab(browser_session: BrowserSession) -> ActionResult:
            """Create a special tab for agent coordination with status display."""
            try:
                # Create new tab
                new_tab = await browser_session.create_tab()
                target_id = new_tab.get('targetId')
                
                if target_id:
                    # Switch to the new tab
                    await browser_session.switch_to_tab(target_id)
                    
                    # Create a simple HTML page for coordination
                    html_content = """
                    data:text/html,
                    <html>
                    <head>
                        <title>Agent Coordination Hub</title>
                        <style>
                            body { font-family: Arial, sans-serif; margin: 20px; background: #f0f0f0; }
                            .status { background: white; padding: 15px; margin: 10px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                            .agent-log { background: #e8f4fd; border-left: 4px solid #2196F3; }
                            h1 { color: #333; }
                            .timestamp { color: #666; font-size: 0.9em; }
                        </style>
                    </head>
                    <body>
                        <h1>🤖 Agent Coordination Hub</h1>
                        <div id="status">
                            <div class="status agent-log">
                                <strong>System:</strong> Coordination hub initialized<br>
                                <span class="timestamp">Agents can use localStorage to communicate</span>
                            </div>
                        </div>
                        <script>
                            // Function to add status updates
                            function addStatus(agent, message) {
                                const statusDiv = document.getElementById('status');
                                const newStatus = document.createElement('div');
                                newStatus.className = 'status agent-log';
                                newStatus.innerHTML = '<strong>' + agent + ':</strong> ' + message + '<br><span class="timestamp">' + new Date().toLocaleTimeString() + '</span>';
                                statusDiv.appendChild(newStatus);
                                statusDiv.scrollTop = statusDiv.scrollHeight;
                            }
                            
                            // Check for updates every second
                            setInterval(() => {
                                const updates = localStorage.getItem('agent_updates');
                                if (updates) {
                                    const updateList = JSON.parse(updates);
                                    const lastCheck = parseInt(localStorage.getItem('last_update_check') || '0');
                                    const newUpdates = updateList.filter(update => update.timestamp > lastCheck);
                                    
                                    newUpdates.forEach(update => {
                                        addStatus(update.agent, update.message);
                                    });
                                    
                                    if (newUpdates.length > 0) {
                                        localStorage.setItem('last_update_check', Date.now().toString());
                                    }
                                }
                            }, 1000);
                        </script>
                    </body>
                    </html>
                    """.replace('\n                    ', '').strip()
                    
                    # Navigate to the HTML content
                    await browser_session.navigate_to(html_content)
                    
                    return ActionResult(
                        extracted_content="Created agent coordination hub tab. Other agents can now use shared data actions to communicate.",
                        include_in_memory=True
                    )
                else:
                    return ActionResult(
                        error="Failed to create coordination tab - no target ID returned",
                        include_in_memory=True
                    )
                    
            except Exception as e:
                return ActionResult(
                    error=f"Failed to create coordination tab: {str(e)}",
                    include_in_memory=True
                )
        
        @self.action("Log agent activity to the coordination system")
        async def log_agent_activity(
            agent_name: str, 
            message: str, 
            browser_session: BrowserSession
        ) -> ActionResult:
            """Log agent activity that will be visible in the coordination hub."""
            try:
                # Get existing updates or create new list
                js_get_updates = "localStorage.getItem('agent_updates') || '[]';"
                
                if browser_session.current_target_id:
                    result = await browser_session.cdp_client.send.Runtime.evaluate(
                        expression=js_get_updates,
                        targetId=browser_session.current_target_id,
                        returnByValue=True
                    )
                    
                    existing_updates = json.loads(result.get('result', {}).get('value', '[]'))
                    
                    # Add new update
                    new_update = {
                        'agent': agent_name,
                        'message': message,
                        'timestamp': int(asyncio.get_event_loop().time() * 1000)  # milliseconds
                    }
                    existing_updates.append(new_update)
                    
                    # Store updated list
                    js_store_updates = f"localStorage.setItem('agent_updates', '{json.dumps(existing_updates)}');"
                    await browser_session.cdp_client.send.Runtime.evaluate(
                        expression=js_store_updates,
                        targetId=browser_session.current_target_id
                    )
                    
                    return ActionResult(
                        extracted_content=f"Logged activity for {agent_name}: {message}",
                        include_in_memory=True
                    )
                else:
                    return ActionResult(
                        error="No active tab to log activity",
                        include_in_memory=True
                    )
                    
            except Exception as e:
                return ActionResult(
                    error=f"Failed to log agent activity: {str(e)}",
                    include_in_memory=True
                )
        
        @self.action("Get browser session information and CDP details")
        async def get_session_info(browser_session: BrowserSession) -> ActionResult:
            """Get detailed information about the current browser session."""
            try:
                info = {
                    "session_id": browser_session.id,
                    "cdp_url": browser_session.cdp_url,
                    "is_local": browser_session.is_local,
                    "current_target_id": browser_session.current_target_id,
                    "profile_settings": {
                        "headless": browser_session.browser_profile.headless,
                        "keep_alive": browser_session.browser_profile.keep_alive,
                        "user_data_dir": str(browser_session.browser_profile.user_data_dir),
                    }
                }
                
                # Get tabs information
                tabs = await browser_session.get_tabs()
                info["total_tabs"] = len(tabs)
                info["tab_titles"] = [tab.get('title', 'Unknown') for tab in tabs[:3]]  # First 3 tabs
                
                result = "Browser Session Information:\n"
                result += f"  Session ID: {info['session_id']}\n"
                result += f"  CDP URL: {info['cdp_url']}\n"
                result += f"  Local Browser: {info['is_local']}\n"
                result += f"  Current Target: {info['current_target_id']}\n"
                result += f"  Total Tabs: {info['total_tabs']}\n"
                result += f"  Profile: headless={info['profile_settings']['headless']}, keep_alive={info['profile_settings']['keep_alive']}\n"
                
                return ActionResult(
                    extracted_content=result,
                    include_in_memory=True
                )
                
            except Exception as e:
                return ActionResult(
                    error=f"Failed to get session info: {str(e)}",
                    include_in_memory=True
                )


async def demonstrate_browser_coordination():
    """Demonstrate how multiple agents can coordinate using shared browser state."""
    
    logger.info("🚀 Setting up shared browser for agent coordination demo...")
    
    # Create shared browser session
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            headless=False,
            keep_alive=True,
            user_data_dir='~/.config/browseruse/profiles/coordination_demo',
        )
    )
    
    await browser_session.start()
    
    try:
        # Create controller with shared browser actions
        controller = BrowserStateManager()
        
        # Agent 1: Coordinator - sets up the coordination system
        logger.info("\n" + "="*60)
        logger.info("🎯 AGENT 1 (Coordinator): Setting up coordination system")
        logger.info("="*60)
        
        coordinator_agent = Agent(
            task="You are the Coordinator agent. Use the create_coordination_tab action to set up "
                 "a coordination hub, then use log_agent_activity to log that you've initialized the system. "
                 "Also store your status using store_shared_data with key 'coordinator_status' and value 'initialized'.",
            llm=ChatOpenAI(model='gpt-4o-mini'),
            browser=browser_session,
            controller=controller,
        )
        
        await coordinator_agent.run()
        await asyncio.sleep(2)
        
        # Agent 2: Data Collector - collects and stores information
        logger.info("\n" + "="*60)
        logger.info("📊 AGENT 2 (Data Collector): Collecting and storing data")
        logger.info("="*60)
        
        data_collector_agent = Agent(
            task="You are the Data Collector agent. First, check the coordinator status using get_shared_data "
                 "with key 'coordinator_status'. Then navigate to https://httpbin.org/json and collect some data. "
                 "Store interesting findings using store_shared_data with key 'collected_data'. "
                 "Log your progress using log_agent_activity with your agent name 'Data Collector'.",
            llm=ChatOpenAI(model='gpt-4o-mini'),
            browser=browser_session,
            controller=controller,
        )
        
        await data_collector_agent.run()
        await asyncio.sleep(2)
        
        # Agent 3: Analyzer - analyzes the collected data
        logger.info("\n" + "="*60)
        logger.info("🔍 AGENT 3 (Analyzer): Analyzing collected data")
        logger.info("="*60)
        
        analyzer_agent = Agent(
            task="You are the Analyzer agent. Use list_shared_data_keys to see what data is available, "
                 "then retrieve the collected data using get_shared_data. Analyze the data and store your "
                 "analysis using store_shared_data with key 'analysis_results'. Log your findings using "
                 "log_agent_activity with your agent name 'Analyzer'.",
            llm=ChatOpenAI(model='gpt-4o-mini'),
            browser=browser_session,
            controller=controller,
        )
        
        await analyzer_agent.run()
        await asyncio.sleep(2)
        
        # Agent 4: Reporter - creates a final report
        logger.info("\n" + "="*60)
        logger.info("📋 AGENT 4 (Reporter): Creating final report")
        logger.info("="*60)
        
        reporter_agent = Agent(
            task="You are the Reporter agent. Use get_session_info to get browser session details, "
                 "then collect all available data using list_shared_data_keys and get_shared_data for each key. "
                 "Create a comprehensive report and store it with key 'final_report'. "
                 "Set the window title using set_window_title to 'Coordination Demo Complete'. "
                 "Log the completion using log_agent_activity with your agent name 'Reporter'.",
            llm=ChatOpenAI(model='gpt-4o-mini'),
            browser=browser_session,
            controller=controller,
        )
        
        await reporter_agent.run()
        
        logger.info("\n" + "="*60)
        logger.info("✅ COORDINATION DEMO COMPLETE")
        logger.info("="*60)
        logger.info("All agents have coordinated successfully using shared browser state!")
        logger.info("Check the coordination tab to see the activity log.")
        logger.info("localStorage contains shared data that was passed between agents.")
        
        input("\nPress Enter to close the browser and exit...")
        
    finally:
        await browser_session.kill()


async def demonstrate_browser_session_sharing():
    """Demonstrate how to access browser session details from custom actions."""
    
    logger.info("🔧 Demonstrating browser session access from custom actions...")
    
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            headless=False,
            keep_alive=True,
        )
    )
    
    await browser_session.start()
    
    try:
        controller = BrowserStateManager()
        
        # Agent that demonstrates session access
        session_demo_agent = Agent(
            task="Use the get_session_info action to show detailed information about this browser session. "
                 "Then navigate to https://example.com and use the browser session actions to demonstrate "
                 "how custom actions can access and manipulate the browser state.",
            llm=ChatOpenAI(model='gpt-4o-mini'),
            browser=browser_session,
            controller=controller,
        )
        
        await session_demo_agent.run()
        
        logger.info("✅ Session access demonstration complete!")
        input("\nPress Enter to close the browser and exit...")
        
    finally:
        await browser_session.kill()


async def main():
    """Main function to run the shared browser action demonstrations."""
    
    print("Browser-Use Shared Browser Actions Demo")
    print("=" * 50)
    print("This demo shows how to create custom controller actions for shared browser management.")
    print()
    print("Choose a demo to run:")
    print("1. Agent coordination using shared browser state (recommended)")
    print("2. Browser session access from custom actions")
    print()
    
    while True:
        choice = input("Enter your choice (1 or 2): ").strip()
        if choice == "1":
            await demonstrate_browser_coordination()
            break
        elif choice == "2":
            await demonstrate_browser_session_sharing()
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