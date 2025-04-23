import os
import sys
import asyncio
import logging
import platform
import subprocess
import argparse
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_cdp_port():
    """
    Extract CDP port in a platform-compatible way
    """
    try:
        if platform.system() == 'Darwin':  # Mac OS
            cmd = "ps -ax | grep -o '\\-\\-remote-debugging-port=[0-9]\\+' | awk -F= '{print $2}'"
        else:  # Linux and others
            cmd = "ps aux | grep -o '\\-\\-remote-debugging-port=[0-9]\\+' | awk -F= '{print $2}'"
            
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.warning(f"Command failed with return code {result.returncode}")
            return None
            
        ports = result.stdout.strip().split('\n')
        ports = [p for p in ports if p]  # Remove empty strings
        
        if not ports:
            logger.warning("No CDP ports found")
            return None
            
        port_counts = {}
        for port in ports:
            if port in port_counts:
                port_counts[port] += 1
            else:
                port_counts[port] = 1
                
        most_common_port = max(port_counts.items(), key=lambda x: x[1])[0]
        logger.info(f"Found CDP port: {most_common_port} (appeared {port_counts[most_common_port]} times)")
        return int(most_common_port)
        
    except Exception as e:
        logger.error(f"Error extracting CDP port: {str(e)}")
        return None

async def take_screenshot(context, name):
    """Take a screenshot and log it"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    page = await context.get_current_page()
    await page.screenshot(path=f"/home/ubuntu/screenshots/naver_test_{name}_{timestamp}.png")
    logger.info(f"Screenshot saved: naver_test_{name}_{timestamp}.png")

async def test_naver_photo_navigation(headless=False, debug=False):
    """Test Naver photo navigation with enhanced features"""
    if debug:
        logging.basicConfig(level=logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    logger.info(f"Testing on platform: {platform.system()}")
    
    cdp_port = extract_cdp_port()
    if cdp_port is None:
        logger.warning("Could not extract CDP port, using default browser")
        cdp_url = None
    else:
        cdp_url = f"http://localhost:{cdp_port}"
        logger.info(f"Using CDP URL: {cdp_url}")
    
    extra_browser_args = []
    if platform.system() == 'Darwin':  # Mac OS
        extra_browser_args.append('--user-agent=' + 
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
    
    logger.info("Creating browser with advanced_mode=True, disable_security=True")
    browser_config = BrowserConfig(
        advanced_mode=True,
        headless=headless,
        cdp_url=cdp_url,
        disable_security=True,  # Enable cross-origin iframe access
        extra_browser_args=extra_browser_args
    )
    
    browser = Browser(config=browser_config)
    
    try:
        async with BrowserContext(browser) as context:
            logger.info("Step 1: Navigating to Naver Maps")
            await context.navigate_to("https://map.naver.com")
            await asyncio.sleep(2)
            await take_screenshot(context, "step1_naver_maps")
            
            logger.info("Step 2: Searching for restaurant '반포식스 덕수궁점'")
            page = await context.get_current_page()
            
            await asyncio.sleep(3)
            
            search_box = await page.query_selector("input[id*='search']")
            if not search_box:
                search_box = await page.query_selector("input[placeholder*='검색']")
            if not search_box:
                search_box = await page.query_selector("input[placeholder*='장소']")
            if not search_box:
                search_box = await page.evaluate_handle("""
                    () => {
                        const inputs = document.querySelectorAll('input');
                        for (const input of inputs) {
                            if (input.placeholder && (
                                input.placeholder.includes('검색') || 
                                input.placeholder.includes('장소') || 
                                input.placeholder.includes('search')
                            )) {
                                return input;
                            }
                        }
                        return document.querySelector('input');  // Last resort: get first input
                    }
                """)
            
            if search_box:
                try:
                    logger.info("Found search box, attempting to interact with it")
                    await search_box.click()  # Focus the search box first
                    await asyncio.sleep(1)
                    await search_box.fill("반포식스 덕수궁점")
                    await asyncio.sleep(1)
                    await search_box.press("Enter")
                    logger.info("Entered restaurant name in search box")
                except Exception as e:
                    logger.warning(f"Error interacting with search box: {str(e)}")
                    logger.info("Using JavaScript fallback to enter restaurant name")
                    await page.evaluate("""
                        () => {
                            const inputs = document.querySelectorAll('input');
                            for (const input of inputs) {
                                if (input.placeholder && (
                                    input.placeholder.includes('검색') || 
                                    input.placeholder.includes('장소') || 
                                    input.placeholder.includes('search')
                                )) {
                                    input.value = '반포식스 덕수궁점';
                                    input.dispatchEvent(new Event('input', { bubbles: true }));
                                    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }));
                                    return;
                                }
                            }
                        }
                    """)
                    logger.info("Used JavaScript fallback to enter restaurant name")
            else:
                logger.warning("Could not find search box")
            
            await asyncio.sleep(3)
            await take_screenshot(context, "step2_search_results")
            
            logger.info("Step 3: Clicking on restaurant result")
            
            restaurant_element = await context.get_element_by_korean_text("반포식스 덕수궁점", 
                                                                 retry_count=3,
                                                                 wait_time=1000)
            
            if restaurant_element:
                logger.info("Found restaurant element by Korean text")
                await page.evaluate("(element) => element.click()", restaurant_element)
            else:
                logger.warning("Could not find restaurant by Korean text, trying alternative method")
                result_elements = await page.query_selector_all("div[role='listitem']")
                if result_elements and len(result_elements) > 0:
                    await result_elements[0].click()
                    logger.info("Clicked on first search result")
                else:
                    logger.warning("Could not find search results")
            
            await asyncio.sleep(3)
            await take_screenshot(context, "step3_restaurant_page")
            
            logger.info("Step 4: Finding and clicking on photo tab")
            
            photo_tab = await context.get_element_by_korean_text("사진", 
                                                       retry_count=3,
                                                       wait_time=1000)
            
            if photo_tab:
                logger.info("Found photo tab by Korean text")
                await page.evaluate("(element) => element.click()", photo_tab)
            else:
                logger.warning("Could not find photo tab by Korean text, trying alternative method")
                tab_elements = await page.query_selector_all("a[role='tab']")
                for tab in tab_elements:
                    tab_text = await tab.text_content()
                    if "사진" in tab_text or "photo" in tab_text.lower():
                        await tab.click()
                        logger.info(f"Clicked on tab with text: {tab_text}")
                        break
            
            await asyncio.sleep(3)
            await take_screenshot(context, "step4_photo_tab")
            
            logger.info("Step 5: Finding and clicking on '외부' category")
            
            exterior_category = await context.get_element_by_korean_text("외부", 
                                                               retry_count=3,
                                                               wait_time=1000)
            
            if exterior_category:
                logger.info("Found '외부' category by Korean text")
                await page.evaluate("(element) => element.click()", exterior_category)
            else:
                logger.warning("Could not find '외부' category by Korean text, trying alternative method")
                category_elements = await page.query_selector_all("button")
                for category in category_elements:
                    category_text = await category.text_content()
                    if "외부" in category_text:
                        await category.click()
                        logger.info(f"Clicked on category with text: {category_text}")
                        break
            
            await asyncio.sleep(3)
            await take_screenshot(context, "step5_exterior_category")
            
            logger.info("Step 6: Finding photo elements")
            
            photo_elements = await context.get_naver_photo_elements(
                deep_search=True,
                retry_count=3,
                wait_time=1000
            )
            
            if photo_elements:
                photo_count = len(photo_elements)
                logger.info(f"Found {photo_count} photo elements")
                
                if photo_count > 0:
                    logger.info("Clicking on first photo")
                    await photo_elements[0].click()
                    logger.info("Clicked on first photo")
                    await asyncio.sleep(3)
                    await take_screenshot(context, "step6_photo_carousel")
                    
                    next_button = await page.query_selector("button[aria-label*='다음']")
                    prev_button = await page.query_selector("button[aria-label*='이전']")
                    
                    if next_button or prev_button:
                        logger.info("✅ Successfully verified photo carousel mode")
                    else:
                        logger.warning("❌ Could not verify photo carousel mode")
            else:
                logger.warning("No photo elements found")
            
            logger.info("Test completed")
            
    except Exception as e:
        logger.error(f"Error during test: {str(e)}")
    finally:
        await browser.close()
        logger.info("Test completed and resources cleaned up")

async def main():
    parser = argparse.ArgumentParser(description='Test Naver photo navigation with enhanced features')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    
    await test_naver_photo_navigation(headless=args.headless, debug=args.debug)

if __name__ == "__main__":
    asyncio.run(main())
