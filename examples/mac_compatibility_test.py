import os
import sys
import asyncio
import logging
import platform
import argparse
import subprocess

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

async def test_mac_compatibility(headless=False):
    """Test Mac compatibility features"""
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
            logger.info("Test 1: Basic navigation")
            await context.navigate_to("https://www.example.com")
            
            page = await context.get_current_page()
            title = await page.title()
            logger.info(f"Page title: {title}")
            
            if "Example" in title:
                logger.info("✅ Basic navigation test passed")
            else:
                logger.warning("❌ Basic navigation test failed")
            
            logger.info("Test 2: Korean text detection")
            await context.navigate_to("https://www.naver.com")
            
            await asyncio.sleep(2)
            
            try:
                korean_element = await context.get_element_by_korean_text("메일", 
                                                                   retry_count=3,
                                                                   wait_time=1000)
                if korean_element:
                    logger.info("✅ Successfully detected Korean text")
                else:
                    logger.warning("❌ Failed to detect Korean text")
            except Exception as e:
                logger.error(f"Error in Korean text detection: {str(e)}")
            
            logger.info("Test 3: Frame detection")
            try:
                frames = page.frames
                logger.info(f"Found {len(frames)} frames on the page")
                
                if len(frames) > 0:
                    logger.info("✅ Frame detection test passed")
                    
                    for i, frame in enumerate(frames):
                        logger.info(f"Frame {i}: {frame.url}")
                else:
                    logger.warning("ℹ️ No frames found on the current page")
            except Exception as e:
                logger.error(f"Error in frame detection: {str(e)}")
            
            logger.info("Test 4: Photo element detection")
            try:
                photo_elements = await context.get_naver_photo_elements(
                    deep_search=True,
                    retry_count=2,
                    wait_time=1000
                )
                
                if photo_elements:
                    photo_count = len(photo_elements)
                    logger.info(f"✅ Successfully detected {photo_count} photo elements")
                else:
                    logger.info("ℹ️ No photo elements found on the current page (expected on Naver homepage)")
            except Exception as e:
                logger.error(f"Error in photo element detection: {str(e)}")
            
            logger.info("Test 5: JavaScript execution")
            try:
                js_result = await page.evaluate("() => navigator.userAgent")
                logger.info(f"User agent: {js_result}")
                
                if js_result and len(js_result) > 0:
                    logger.info("✅ JavaScript execution test passed")
                else:
                    logger.warning("❌ JavaScript execution test failed")
            except Exception as e:
                logger.error(f"Error in JavaScript execution: {str(e)}")
            
            logger.info("Test 6: Timeout values")
            try:
                await context.navigate_to("https://www.google.com")
                logger.info("✅ Navigation with increased timeout successful")
            except Exception as e:
                logger.error(f"Error in timeout test: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error during test: {str(e)}")
    finally:
        await browser.close()
        logger.info("Test completed and resources cleaned up")

async def main():
    parser = argparse.ArgumentParser(description='Test Mac compatibility for browser-use')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    args = parser.parse_args()
    
    await test_mac_compatibility(headless=args.headless)

if __name__ == "__main__":
    asyncio.run(main())
