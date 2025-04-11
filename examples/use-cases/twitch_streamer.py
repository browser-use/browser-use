#Opens twitch and starts playing the top viewed stream of minecraft or any other game of your choice 
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from browser_use import Agent, Browser, BrowserConfig, Controller

load_dotenv()

controller = Controller()

@controller.action('Navigate to Twitch')
async def go_to_twitch(browser):
    await browser.goto('https://www.twitch.tv')
    await asyncio.sleep(3)
    
    # Close age gate if present
    try:
        age_gate = await browser.get_dom_element_by_selector('[data-a-target="player-overlay-click-handler"]')
        if age_gate:
            await browser.press_key('Escape')
    except:
        pass
    return "Reached Twitch homepage"
game = "Minecraft"
@controller.action('Search for Minecraft category')
async def search_minecraft(browser):
    await browser.goto(f'https://www.twitch.tv/directory/game/{game}')
    await asyncio.sleep(5)
    return f"Loaded {game} category"

@controller.action('Select most viewed stream')
async def select_top_stream(browser):
    stream_card = await browser.get_dom_element_by_selector('[data-a-target="preview-card-title-link"]:first-child')
    if not stream_card:
        return "No streams found"
    
    await stream_card.click()
    await asyncio.sleep(5)
    
    try:
        confirm_btn = await browser.get_dom_element_by_selector('[data-a-target="player-overlay-mature-accept"]')
        if confirm_btn:
            await confirm_btn.click()
    except:
        pass
    
    play_button = await browser.get_dom_element_by_selector('[data-a-target="player-play-pause-button"]')
    if play_button:
        await play_button.click()
    
    return "Stream started"

browser = Browser(
    config=BrowserConfig(
        chrome_instance_path='C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe',
        headless=False
    )
)

async def main():
    # Add language model instance
    llm = ChatOpenAI(
        model='gpt-4o',
        temperature=0
    )

    agent = Agent(
        task=f"Twitch Automation:\n"
             f"1. Navigate to Twitch.tv\n"
             f"2. Load {game} category\n"
             f"3. Sort by the view count\n"
             f"4. Select the top stream\n"
             f"5. Start playback",
        llm=llm,  # Add this required parameter
        controller=controller,
        browser=browser,
        use_vision=True
    )

    await agent.run()

if __name__ == '__main__':
    asyncio.run(main())