# Tweets a random interesting fact about Radiohead on twitter 
import asyncio
from browser_use import Agent, Browser, BrowserConfig
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()  # Load Twitter credentials from .env file

async def main():
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
    
    # Run the agent
    print("Searching for Radiohead facts and posting to Twitter...")
    await agent.run()
    
    # Close browser
    await browser.close()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
