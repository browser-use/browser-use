"""
Test script to verify iframe support with Naver Maps restaurant listing.
"""

import asyncio
import os
import sys
from urllib.parse import urlparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig


async def test_naver_maps_iframe():
    """Test iframe support with Naver Maps restaurant listing."""
    print("Starting Naver Maps iframe test...")
    
    cdp_port = 29229  # From the shell command output
    cdp_url = f"http://localhost:{cdp_port}"
    print(f"Using CDP URL: {cdp_url}")
    
    browser = Browser(
        config=BrowserConfig(
            headless=False,
            cdp_url=cdp_url,  # Connect to existing browser instead of launching new one
        )
    )
    
    context = BrowserContext(
        browser=browser,
        config=BrowserContextConfig(
            allowed_domains=["naver.com", "map.naver.com", "pcmap.place.naver.com"],
        )
    )
    
    try:
        url = "https://map.naver.com/p/search/%EB%B0%98%ED%8F%AC%EC%8B%9D%EC%8A%A4%20%EB%8D%95%EC%88%98%EA%B6%81%EC%A0%90/place/1188320878?c=15.00,0,0,0,dh&isCorrectAnswer=true"
        print(f"Navigating to: {url}")
        await context.navigate_to(url)
        
        print("Waiting for page to load...")
        await asyncio.sleep(5)
        
        print("\nGetting page frames...")
        page = await context.get_current_page()
        frames = page.frames
        print(f"Found {len(frames)} frames")
        
        for i, frame in enumerate(frames):
            print(f"Frame {i}: {frame.url}")
        
        print("\nLooking for pcmap.place.naver.com frame...")
        pcmap_frame = None
        for frame in frames:
            if "pcmap.place.naver.com" in frame.url:
                pcmap_frame = frame
                print(f"Found pcmap frame: {frame.url}")
                break
        
        if not pcmap_frame:
            print("pcmap frame not found")
        
        print("\nLooking for photo elements in the main frame...")
        try:
            main_photo_elements = await context.execute_javascript("""
                const photoElements = Array.from(document.querySelectorAll('*')).filter(el => 
                    el.textContent && (el.textContent.includes('내부') || el.textContent.includes('외부'))
                );
                return photoElements.map(el => ({
                    tagName: el.tagName,
                    text: el.textContent.trim(),
                    className: el.className
                }));
            """)
            print(f"Found {len(main_photo_elements)} potential photo elements in main frame")
            for i, element in enumerate(main_photo_elements):
                print(f"Element {i}: {element}")
        except Exception as e:
            print(f"Error finding photo elements in main frame: {e}")
        
        if pcmap_frame:
            print("\nLooking for photo elements in the pcmap frame...")
            try:
                result = await pcmap_frame.evaluate("""
                    const photoElements = Array.from(document.querySelectorAll('*')).filter(el => 
                        el.textContent && (el.textContent.includes('내부') || el.textContent.includes('외부'))
                    );
                    return photoElements.map(el => ({
                        tagName: el.tagName,
                        text: el.textContent.trim(),
                        className: el.className
                    }));
                """)
                print(f"Found {len(result)} potential photo elements in pcmap frame")
                for i, element in enumerate(result):
                    print(f"Element {i}: {element}")
            except Exception as e:
                print(f"Error finding photo elements in pcmap frame: {e}")
        
        print("\nTest completed. Press Enter to close the browser...")
        await asyncio.sleep(30)  # Keep browser open for 30 seconds
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_naver_maps_iframe())
