import asyncio
import os
from typing import Optional
import json
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from browser_use import Agent, Browser, BrowserConfig, Controller, Config

# Load environment variables from .env file
load_dotenv()

# Initialize controller for custom actions
controller = Controller()

@controller.action('Ask user for information')
def ask_human(question: str, display_question: bool = True) -> str:
    return input(f'\n{question}\nInput: ') if display_question else input()

async def main(browser=None, context=None):
    try:
        # Set telemetry based on environment variable
        Config.telemetry_enabled = os.getenv('ANONYMIZED_TELEMETRY', 'true').lower() == 'true'
        
        # Get task from user
        print("\nWelcome to Browser-Use CLI!")
        print("----------------------------")
        task = input("\nPlease enter your task (e.g. 'Find flights from NYC to London'): ")
        
        # Analyze if task is just navigation
        task_lower = task.lower()
        if task_lower.startswith(('go to ', 'open ', 'navigate to ')):
            # Extract the website
            website = task_lower.replace('go to ', '').replace('open ', '').replace('navigate to ', '').strip()
            # Add https:// if needed
            if not website.startswith(('http://', 'https://')):
                website = f'https://www.{website}.com'
            
            print(f"\nNavigating to {website}...")
            page = await context.new_page()
            await page.goto(website)
            result = f"Successfully navigated to {website}"
            history = []  # Empty history for simple navigation
        else:
            # Initialize agent with task
            agent = Agent(
                task=task,
                llm=ChatOpenAI(model="gpt-4o"),  # Using standard GPT-4 model
                controller=controller
            )
            print("\nExecuting task...")
            try:
                history = await agent.run()
                if not history:
                    result = "No result returned from agent"
                else:
                    # Try to get structured result
                    try:
                        result = history[-1].result
                    except (AttributeError, IndexError):
                        # Fallback to string representation
                        result = str(history[-1]) if history else "No result"
            except Exception as e:
                print(f"\nError during task execution: {str(e)}")
                result = f"Task failed: {str(e)}"
                history = []

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
        
        # Ask if user wants to save result
        save_choice = input("\nWould you like to save the result to a file? (yes/no): ").lower()
        if save_choice == 'yes':
            filename = input("\nEnter filename (default: result.txt): ").strip() or "result.txt"
            try:
                # Try to save as JSON if result is structured
                try:
                    with open(filename, 'w', encoding='utf-8') as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
                except (TypeError, ValueError):
                    # Fallback to string if not JSON serializable
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(str(result))
                print(f"\nResult saved to {filename}")
            except Exception as e:
                print(f"\nError saving file: {str(e)}")
        
        # Ask if user wants to continue
        continue_choice = input("\nDo you want to continue with another task? (yes/no): ").lower()
        if continue_choice == 'yes':
            await main(browser=browser, context=context)  # Reuse browser and context
            return  # Return here to prevent double cleanup
            
    except Exception as e:
        print(f"\nError: {str(e)}")
        if "OPENAI_API_KEY" in str(e):
            print("\nPlease make sure you have set up your OPENAI_API_KEY in .env file")
        elif "ModuleNotFoundError" in str(e):
            print("\nPlease install required dependencies:")
            print("pip install -r requirements.txt")
            print("playwright install")
    finally:
        # Cleanup
        if context:
            await context.close()
        if browser:
            await browser.close()

async def run_cli():
    browser = None
    context = None
    try:
        await main(browser, context)
    except KeyboardInterrupt:
        print("\nExiting gracefully...")
    except Exception as e:
        print(f"\nFatal error: {str(e)}")
    finally:
        print("\nGoodbye!")

if __name__ == "__main__":
    asyncio.run(run_cli())
