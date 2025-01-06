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
        # Configure browser settings
        # Configure Browser Use settings
        telemetry_enabled = os.getenv('ANONYMIZED_TELEMETRY', 'true').lower() == 'true'
        Config.telemetry_enabled = telemetry_enabled

        # Configure browser settings
        browser_config = BrowserConfig(
            headless=False,  # Run in visible mode
            disable_security=False,  # Keep security features enabled
            viewport={'width': 1280, 'height': 720},
            locale='en-US'
        )

        if browser is None or context is None:
            print("\nInitializing browser...")
            # Initialize shared browser instance with retries
            max_retries = 3
            retry_count = 0
            while retry_count < max_retries:
                try:
                    browser = Browser(config=browser_config)
                    await browser.start()
                    context = browser.context
                    break
                except Exception as e:
                    retry_count += 1
                    if retry_count == max_retries:
                        print(f"\nFailed to initialize browser after {max_retries} attempts.")
                        print(f"Error details: {str(e)}")
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
            # Full agent for complex tasks
            agent = Agent(
                task=task,
                llm=ChatOpenAI(model="gpt-4o"),  # Using GPT-4o model
                controller=controller,
                browser_context=context  # Using context instead of browser directly
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
            
    except KeyError as e:
        print(f"\nEnvironment variable error: {str(e)}")
        print("\nPlease make sure you have set up your OPENAI_API_KEY in .env file")
    except ImportError as e:
        print(f"\nDependency error: {str(e)}")
        print("\nPlease make sure you have installed all required dependencies")
        print("\nTry running: pip install -r requirements.txt")
        print("And: playwright install")
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
