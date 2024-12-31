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
    # Configure browser settings
    browser_config = BrowserConfig(
        headless=True,  # Run in headless mode by default
        disable_security=False,  # Keep security features enabled
    )
    
    # Initialize shared browser instance
    browser = Browser(config=browser_config)
    # Get task from user
    print("\nWelcome to Browser-Use CLI!")
    print("----------------------------")
    task = input("\nPlease enter your task (e.g. 'Find flights from NYC to London'): ")
    
    # Initialize the agent
    try:
        async with browser.new_context() as context:
            agent = Agent(
                task=task,
                llm=ChatOpenAI(model="gpt-4o"),
                controller=controller,
                browser_context=context
            )
            
            print("\nExecuting task...")
            history = await agent.run()
            result = history[-1].result if history else "No result"
            
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
    except Exception as e:
        print(f"\nUnexpected error: {str(e)}")
        print("\nPlease check:")
        print("1. Your OPENAI_API_KEY is valid")
        print("2. All dependencies are installed")
        print("3. Playwright is installed ('playwright install')")
        
        # Ask if user wants to exit even after error
        exit_choice = input("\nDo you want to exit? (yes/no): ").lower()
        if exit_choice != 'yes':
            await main()  # Restart the main function if user doesn't want to exit

if __name__ == "__main__":
    asyncio.run(main())
