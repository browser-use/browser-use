# Tweets a random interesting fact about Radiohead on twitter 
import asyncio
import logging
import sys
from browser_use import Agent, Browser, BrowserConfig
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from playwright.async_api import TimeoutError, Error as PlaywrightError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()  # Load Twitter credentials from .env file

async def main():
    browser = None
    try:
        # Initialize browser
        browser = Browser(config=BrowserConfig(headless=False, chrome_instance_path="C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"))
        
        # Create agent with task to search for Radiohead facts and post one to Twitter
        agent = Agent(
            task="1. Search for interesting facts about Radiohead that most people don't know\n"
                 "2. Choose the most interesting fact you found\n"
                 "3. Log into Twitter/X\n"
                 "4. Create a new post containing this interesting Radiohead fact\n"
                 "5. Add the hashtag #Radiohead to the post\n"
                 "6. Post the tweet",
            llm=ChatOpenAI(model="gpt-4o"),
            browser=browser,
            use_vision=True
        )
        
        logger.info("Searching for Radiohead facts and posting to Twitter...")
        await agent.run()
        logger.info("Tweet posted successfully!")
        
    except TimeoutError as e:
        logger.error(f"Timeout error during browser automation: {str(e)}")
        logger.info("The operation timed out. This could be due to slow internet or Twitter being unresponsive.")
    except PlaywrightError as e:
        logger.error(f"Playwright error during browser automation: {str(e)}")
        logger.info("There was an issue with the browser automation. Please check your browser configuration.")
    except Exception as e:
        logger.error(f"Unexpected error during the process: {str(e)}")
        logger.info("An unexpected error occurred. Please check the logs for details.")
    finally:
        # Ensure browser is closed even if an error occurs
        if browser:
            try:
                await browser.close()
                logger.info("Browser closed successfully")
            except Exception as e:
                logger.error(f"Error closing browser: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
