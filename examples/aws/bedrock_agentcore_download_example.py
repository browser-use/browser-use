"""
AWS Bedrock AgentCore Browser Download Example

This example demonstrates how to use browser-use with AWS Bedrock AgentCore's BrowserClient
to download files in remote browser environments. The enhanced browser-use version includes
HTTP client fallback for downloads when browser file dialogs are not available.

Prerequisites:
- AWS credentials configured
- bedrock-agentcore package installed
- Enhanced browser-use with download functionality

Key Features:
- Remote browser file downloads via HTTP client
- Agent download awareness and progress tracking
- Automatic PDF download handling
- Large file download support with progress monitoring
"""

import asyncio
from contextlib import suppress

from bedrock_agentcore.tools.browser_client import BrowserClient
from boto3.session import Session
from rich.console import Console

from browser_use import Agent, Browser, BrowserProfile
from browser_use.llm import ChatAnthropicBedrock

console = Console()

async def main():
    """
    Main function demonstrating file download with AWS Bedrock AgentCore BrowserClient.
    
    This example shows how to:
    1. Set up a remote browser session with download capabilities
    2. Configure the agent for file downloads
    3. Execute download tasks with progress monitoring
    4. Handle cleanup properly
    """
    
    # Initialize AWS session and get region
    boto_session = Session()
    region = boto_session.region_name or 'us-west-2'  # Default region if none configured
    console.print(f"[blue]Using AWS region: {region}[/blue]")
    
    # Create BrowserClient for remote browser management
    client = BrowserClient(region)
    client.start(viewport={'width': 1920, 'height': 1080})
    console.print("[green]✅ BrowserClient started[/green]")

    # Generate WebSocket URL and headers for browser connection
    ws_url, headers = client.generate_ws_headers()
    browser_session = None

    try:
        # Configure browser profile with download enhancements
        browser_profile = BrowserProfile(
            headers=headers,                          # Authentication headers from BrowserClient
            downloads_path="./downloads",            # Local directory for downloaded files
            download_from_remote_browser=True,       # Enable HTTP client downloads (key feature!)
            auto_download_pdfs=True                  # Automatically download PDFs when encountered
        )
        console.print("[green]✅ Browser profile configured with download enhancements[/green]")

        # Create browser session with remote CDP connection
        browser_session = Browser(
            cdp_url=ws_url,                         # WebSocket URL to remote browser
            browser_profile=browser_profile,         # Enhanced profile with download capabilities
            keep_alive=True                         # Maintain connection for multiple operations
        )
        
        await browser_session.start()
        console.print("[green]✅ Browser session started[/green]")
        
        # Initialize Bedrock LLM for agent
        bedrock_chat = ChatAnthropicBedrock(
            model='us.anthropic.claude-3-7-sonnet-20250219-v1:0',  # Latest Claude model
            aws_region='us-west-2'                                  # Bedrock region
        )
        console.print("[green]✅ Bedrock LLM initialized[/green]")

        # Define download task - agent will handle the entire download process
        task = "Go to https://proof.ovh.net/files and download the 100 MB file. Please wait for the download to finish and tell me when done."
        
        # Alternative tasks for different download scenarios:
        # task = "Go to https://www.adobe.com/support/products/enterprise/knowledgecenter/media/c4611_sample_explain.pdf. Click on the download link on the browser to download the file."
        # task = "Go to https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
        # task = "Go to https://www.rd.usda.gov/sites/default/files/pdf-sample_0.pdf."

        console.print(f"[yellow]📋 Task: {task}[/yellow]")

        # Create agent with download-enhanced browser session
        agent = Agent(
            task=task,                              # Download instruction
            llm=bedrock_chat,                       # Bedrock LLM for decision making
            browser_session=browser_session,        # Enhanced browser with download capabilities
            llm_timeout=300                         # Extended timeout for download operations
        )
        
        console.print("[blue]🤖 Starting agent execution...[/blue]")
        
        # Execute the download task
        # The agent will:
        # 1. Navigate to the specified URL
        # 2. Identify downloadable content
        # 3. Use HTTP client to download files (bypassing browser dialogs)
        # 4. Monitor download progress and report completion
        # 5. Handle any download failures gracefully
        result = await agent.run()
        
        console.print("[green]✅ Agent execution completed[/green]")
        console.print(f"[cyan]Result: {result}[/cyan]")

    except Exception as e:
        console.print(f"[red]❌ Error during execution: {e}[/red]")
        raise
        
    finally:
        # Clean up resources
        if browser_session:
            with suppress(Exception):
                await browser_session.stop()
                console.print("[yellow]🧹 Browser session stopped[/yellow]")
        
        client.stop()
        console.print("[yellow]🧹 BrowserClient stopped[/yellow]")

if __name__ == "__main__":
    console.print("[bold blue]🚀 Starting AWS Bedrock AgentCore Browser Download Example[/bold blue]")
    asyncio.run(main())
    console.print("[bold green]🎉 Example completed![/bold green]")
