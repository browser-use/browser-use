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

async def verify_enhancements(headless=False):
    """Verify Mac compatibility enhancements"""
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
            logger.info("Test 1: Verify advanced_mode is enabled")
            if browser.config.advanced_mode:
                logger.info("✅ advanced_mode is enabled")
            else:
                logger.warning("❌ advanced_mode is not enabled")
            
            logger.info("Test 2: Verify disable_security is enabled")
            if browser.config.disable_security:
                logger.info("✅ disable_security is enabled")
            else:
                logger.warning("❌ disable_security is not enabled")
            
            logger.info("Test 3: Verify Korean text detection method exists")
            if hasattr(context, 'get_element_by_korean_text'):
                logger.info("✅ get_element_by_korean_text method exists")
            else:
                logger.warning("❌ get_element_by_korean_text method does not exist")
            
            logger.info("Test 4: Verify get_naver_photo_elements method exists")
            if hasattr(context, 'get_naver_photo_elements'):
                logger.info("✅ get_naver_photo_elements method exists")
            else:
                logger.warning("❌ get_naver_photo_elements method does not exist")
            
            logger.info("Test 5: Verify navigation to a simple site")
            await context.navigate_to("https://www.example.com")
            
            page = await context.get_current_page()
            title = await page.title()
            logger.info(f"Page title: {title}")
            
            if "Example" in title:
                logger.info("✅ Navigation to example.com successful")
            else:
                logger.warning("❌ Navigation to example.com failed")
            
            logger.info("Test 6: Verify JavaScript execution")
            try:
                js_result = await page.evaluate("() => navigator.userAgent")
                logger.info(f"User agent: {js_result}")
                
                if js_result and len(js_result) > 0:
                    logger.info("✅ JavaScript execution successful")
                else:
                    logger.warning("❌ JavaScript execution failed")
            except Exception as e:
                logger.error(f"Error in JavaScript execution: {str(e)}")
            
            logger.info("Test 7: Verify timeout values")
            try:
                config = context.config
                logger.info(f"wait_for_network_idle_page_load_time: {config.wait_for_network_idle_page_load_time}")
                logger.info(f"maximum_wait_page_load_time: {config.maximum_wait_page_load_time}")
                
                if config.wait_for_network_idle_page_load_time >= 1.0 and config.maximum_wait_page_load_time >= 8.0:
                    logger.info("✅ Timeout values are increased for Mac compatibility")
                else:
                    logger.warning("❌ Timeout values are not increased for Mac compatibility")
            except Exception as e:
                logger.error(f"Error checking timeout values: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error during verification: {str(e)}")
    finally:
        await browser.close()
        logger.info("Verification completed and resources cleaned up")

async def main():
    parser = argparse.ArgumentParser(description='Verify Mac compatibility enhancements')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    args = parser.parse_args()
    
    await verify_enhancements(headless=args.headless)

if __name__ == "__main__":
    asyncio.run(main())
