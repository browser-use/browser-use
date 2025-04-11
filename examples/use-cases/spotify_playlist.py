import asyncio
import logging
import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

load_dotenv()
controller = Controller()

class Artist(BaseModel):
    name: str

class Track(BaseModel):
    name: str
    artist: str

@controller.action('Read artist list')
def read_artists():
    try:
        with open('artists.txt', 'r') as f:
            artists = [line.strip() for line in f.readlines() if line.strip()]
        return ActionResult(artists=artists)
    except FileNotFoundError:
        # Create a sample file if it doesn't exist
        sample_artists = ["Taylor Swift", "Ed Sheeran", "Billie Eilish", "The Weeknd", "Dua Lipa"]
        with open('artists.txt', 'w') as f:
            f.write('\n'.join(sample_artists))
        return ActionResult(artists=sample_artists)

@controller.action('Open Spotify')
async def open_spotify(browser: BrowserContext):
    await browser.goto('https://open.spotify.com/')
    await asyncio.sleep(3)
    
    # Handle initial cookie popup
    try:
        accept_btn = await browser.get_dom_element_by_selector('[data-testid="cookie-policy-manage-dialog-accept-button"]')
        if accept_btn:
            await accept_btn.click()
            await asyncio.sleep(1)
    except:
        pass
    
    return "Opened Spotify successfully"

@controller.action('Search artist')
async def search_artist(browser: BrowserContext, artist_name: str):
    search_btn = await browser.get_dom_element_by_selector('[data-testid="search-input"]')
    await search_btn.click()
    await browser.type_text('[data-testid="search-input"]', artist_name)
    await asyncio.sleep(2)
    
    # Select artist from results
    try:
        # Try to find artist using aria-label
        artist_result = await browser.get_dom_element_by_selector(f'[aria-label="{artist_name}"]')
        if not artist_result:
            # Try alternative selector for artist results
            artist_results = await browser.get_dom_elements_by_selector('[data-testid="tracklist-row"]')
            if artist_results and len(artist_results) > 0:
                artist_result = artist_results[0]
            else:
                return ActionResult(error=f"Artist {artist_name} not found")
        
        await artist_result.click()
        await asyncio.sleep(3)
        return f"Navigated to {artist_name}'s page"
    except Exception as e:
        return ActionResult(error=f"Error finding artist: {str(e)}")

@controller.action('Get top songs')
async def get_top_songs(browser: BrowserContext):
    # Get popular tracks
    tracks = []
    try:
        song_elements = await browser.get_dom_elements_by_selector('[data-testid="tracklist-row"]')
        
        for element in song_elements[:5]:  # Top 5 tracks
            name_el = await element.query_selector('[data-testid="internal-track-link"]')
            track_name = await name_el.get_text()
            artist_el = await element.query_selector('[data-testid="track-row-artist"]')
            artist_name = await artist_el.get_text()
            tracks.append(Track(name=track_name, artist=artist_name))
        
        return tracks
    except Exception as e:
        return ActionResult(error=f"Error getting songs: {str(e)}")

browser = Browser(
    config=BrowserConfig(
        chrome_instance_path='C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe',
        headless=False,
    )
)

async def main():
    model = ChatOpenAI(model='gpt-4o')
    
    agent = Agent(
        task="Spotify Artist Search Workflow:\n"
             "1. Open Spotify website\n"
             "2. Read artists from artists.txt\n"
             "3. For each artist:\n"
             "   a. Search and navigate to artist page\n"
             "   b. Collect top 5 songs\n"
             "   c. Add the first song to the playlist\n"
             "   d. Return back to the artist page\n"
             "   e. Add the next song to the playlist\n"
             "   f. Return back to the artist page\n"
             "   g. Add the next song to the playlist\n"
             "   h. Return back to the artist page\n"
             "   i. Add the next song to the playlist\n"
             "   j. Return back to the artist page\n"
             "   k. Add the next song to the playlist\n"
             "   l. Return to search page for next artist",
             
        llm=model,
        controller=controller,
        browser=browser,
        use_vision=True
    )

    await agent.run()
    
    # Close the browser when finished
    await browser.close()

if __name__ == '__main__':
    asyncio.run(main())