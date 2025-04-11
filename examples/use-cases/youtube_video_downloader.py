#for this file initially run this command : pip install yt-dlp
import asyncio
import os
import subprocess
from typing import Optional
from urllib.parse import quote_plus

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

load_dotenv()
controller = Controller()

class SearchQuery(BaseModel):
    query: str = "Large Language Models"
    download_dir: str = os.path.join(os.getcwd(), "downloads")

@controller.action('Set search parameters', param_model=SearchQuery)
def set_search_params(params: SearchQuery):
    os.makedirs(params.download_dir, exist_ok=True)
    return params

@controller.action('Go to YouTube search results')
async def go_to_search_results(browser: BrowserContext, query: str):
    # Encode the query for URL
    encoded_query = quote_plus(query)
    
    # Navigate directly to search results
    await browser.goto(f'https://www.youtube.com/results?search_query={encoded_query}')
    await asyncio.sleep(3)
    
    # Accept cookies if prompt appears
    try:
        accept_btn = await browser.get_dom_element_by_selector('button[aria-label="Accept all"]')
        if accept_btn:
            await accept_btn.click()
            await asyncio.sleep(1)
    except:
        pass
    
    return f"Navigated to YouTube search results for: {query}"

@controller.action('Sort by view count')
async def sort_by_views(browser: BrowserContext):
    try:
        # Click on filter button
        filter_btn = await browser.get_dom_element_by_selector('button[aria-label="Filters"]')
        await filter_btn.click()
        await asyncio.sleep(1)
        
        # Find and click on "View count" option
        view_count_option = await browser.get_dom_element_by_selector('span[role="presentation"]:has-text("View count")')
        await view_count_option.click()
        await asyncio.sleep(3)
        
        return "Sorted results by view count"
    except Exception as e:
        return ActionResult(error=f"Error sorting by views: {str(e)}")

@controller.action('Get top video URL and info')
async def get_top_video(browser: BrowserContext):
    try:
        # Find the first video in the results
        video_element = await browser.get_dom_element_by_selector('a#video-title')
        
        # Get the URL of the video
        video_url = await video_element.get_attribute('href')
        if video_url.startswith('/watch'):
            full_url = f"https://www.youtube.com{video_url}"
        else:
            full_url = video_url
        
        # Get video title
        video_title = await video_element.get_text()
        
        # Try to get channel name
        try:
            channel_element = await browser.get_dom_element_by_selector('#channel-name')
            channel_name = await channel_element.get_text()
        except:
            channel_name = "Unknown channel"
            
        # Try to get view count
        try:
            metadata_element = await browser.get_dom_element_by_selector('#metadata-line')
            view_info = await metadata_element.get_text()
        except:
            view_info = "Unknown views"
        
        return ActionResult(
            video_url=full_url, 
            video_title=video_title,
            channel_name=channel_name,
            view_info=view_info
        )
    except Exception as e:
        return ActionResult(error=f"Error getting video URL: {str(e)}")

@controller.action('Download video using yt-dlp')
def download_video_with_ytdlp(video_url: str, download_dir: str):
    """
    Download YouTube video using yt-dlp command line tool.
    
    This function uses yt-dlp which is a powerful command-line download manager 
    specialized for YouTube and many other video platforms. It offers:
    
    - Support for various quality options up to 8K
    - Ability to download entire playlists
    - Extraction of audio in multiple formats
    - Support for subtitles
    - Fast downloads with multiple connections
    
    The function runs yt-dlp with the specified output directory and video URL.
    """
    try:
        # Make sure the download directory exists
        os.makedirs(download_dir, exist_ok=True)
        
        # Prepare the command
        cmd = ["yt-dlp", "-P", download_dir, video_url]
        
        # Execute the command and get the output
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            return f"Successfully downloaded video to {download_dir}\nOutput: {result.stdout[:500]}..."
        else:
            return ActionResult(error=f"Error downloading video: {result.stderr}")
            
    except Exception as e:
        return ActionResult(error=f"Exception while downloading: {str(e)}")

browser = Browser(
    config=BrowserConfig(
        # You can specify your browser path here if needed
        # chrome_instance_path='C:/Program Files/Google/Chrome/Application/chrome.exe',
        headless=False,
    )
)

async def main():
    model = ChatOpenAI(model='gpt-4o')
    
    agent = Agent(
        task="YouTube Video Downloader Workflow:\n"
             "1. Set search parameters (default: 'Large Language Models')\n"
             "2. Navigate directly to YouTube search results\n"
             "3. Sort results by view count\n"
             "4. Get the URL and information about the top video\n"
             "5. Download the video using yt-dlp command line tool\n"
             "   - The video will be downloaded in best quality\n"
             "   - Files will be saved to the 'downloads' folder in current directory\n"
             "   - yt-dlp must be installed on your system",
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
