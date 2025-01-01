import asyncio
from langchain_openai import ChatOpenAI
from browser_use import Agent
from browser_use import Browser, BrowserConfig
from browser_use import Controller
import os
from dotenv import load_dotenv
from typing import Optional
from pydantic import BaseModel

# Load environment variables from .env file
load_dotenv()

# Initialize controller for custom actions
controller = Controller()

@controller.action('Ask user for information')
def ask_human(question: str, display_question: bool = True) -> str:
    return input(f'\n{question}\nInput: ') if display_question else input()

async def main():
    browser = None
    context = None
    try:
        # Configure browser settings
        chrome_paths = [
            'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
            'C:\\Program Files\\Google Chrome\\chrome.exe',
            'C:\\Program Files (x86)\\Google Chrome\\chrome.exe',
            os.environ.get('CHROME_PATH')
        ]
        
        chrome_path = None
        for path in chrome_paths:
            if path and os.path.exists(path):
                chrome_path = path
                break
                
        if not chrome_path:
            raise FileNotFoundError("Could not find Chrome executable. Please set CHROME_PATH environment variable.")
            
        browser_config = BrowserConfig(
            headless=False,  # Run in visible mode
            disable_security=False,  # Keep security features enabled
            chrome_instance_path=chrome_path
        )
        
        # Initialize shared browser instance with retries
        max_retries = 3
        retry_count = 0
        while retry_count < max_retries:
            try:
                browser = Browser(config=browser_config)
                break
            except Exception as e:
                retry_count += 1
                if retry_count == max_retries:
                    print(f"\nFailed to initialize browser after {max_retries} attempts: {str(e)}")
                    print("Please ensure:")
                    print("1. Chrome is completely closed")
                    print("2. No other Chrome automation scripts are running")
                    print("3. Chrome is properly installed at the specified path")
                    return
                print(f"\nRetry {retry_count}/{max_retries}: Attempting to initialize browser again...")
                await asyncio.sleep(2)  # Wait before retrying
        
        # Get task from user
        print("\nWelcome to Browser-Use CLI!")
        print("----------------------------")
        task = input("\nPlease enter your task (e.g. 'Find flights from NYC to London'): ")
        
        # Initialize the agent
        context = await browser.new_context()
        agent = Agent(
            task=task,
            llm=ChatOpenAI(model="gpt-4o"),
            controller=controller,
            browser=browser
        )
        
        print("\nExecuting task...")
        history = await agent.run()
        result = history[-1].result if history and len(history) > 0 else "No result"
        
        # Print XPath history if requested
        show_history = input("\nWould you like to see the action history? (yes/no): ").lower()
        if show_history == 'yes':
            print("\nAction History:")
            for entry in history:
                print(f"- Action: {entry.action}")
                if entry.xpath:
                    print(f"  XPath: {entry.xpath}")
        print("\nTask completed!")
        print("\nResult:", result)
        
        # Ask if user wants to exit
        exit_choice = input("\nDo you want to exit? (yes/no): ").lower()
        if exit_choice != 'yes':
            await main()  # Restart the main function if user doesn't want to exit
            
    except KeyError as e:
        print(f"\nEnvironment variable error: {str(e)}")
        print("\nPlease make sure you have set up your OPENAI_API_KEY in .env file")
    except ImportError as e:
        print(f"\nDependency error: {str(e)}")
        print("\nPlease make sure you have installed all required dependencies")
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
    except Exception as e:
        print(f"\nUnexpected error: {str(e)}")
        print("\nPlease check:")
        print("1. Your OPENAI_API_KEY is valid")
        print("2. All dependencies are installed")
        print("3. Playwright is installed ('playwright install')")
    finally:
        # Cleanup
        if context:
            await context.close()
        if browser:
            await browser.close()

async def run_cli():
    try:
        await main()
    except KeyboardInterrupt:
        print("\nExiting gracefully...")
    except Exception as e:
        print(f"\nFatal error: {str(e)}")
    finally:
        print("\nGoodbye!")

if __name__ == "__main__":
    asyncio.run(run_cli())
