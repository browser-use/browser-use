import os
import sys
import subprocess
import re
import platform
import time
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging
import argparse

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from pydantic import SecretStr

from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

DEFAULT_TASK = 'Go to Naver Maps and search for the restaurant - 반포식스 덕수궁점 and click on the photo to get to the photo categories and then select the 외부 category and then click on the first photo from the 외부 category and verify you are in photo carousel mode'

SCREENSHOT_DIR = os.path.join(os.path.expanduser("~"), "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

async def take_screenshot(context, name):
    """Take a screenshot and log it"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    page = await context.get_current_page()
    await page.screenshot(path=f"{SCREENSHOT_DIR}/advance_{name}_{timestamp}.png")
    logger.info(f"Screenshot saved: advance_{name}_{timestamp}.png")

async def authenticate_naver(browser):
    """
    Authenticate with Naver using credentials from environment variables
    """
    username = os.environ.get("NAVER_USERNAME")
    password = os.environ.get("NAVER_PASSWORD")
    
    if not username or not password:
        logger.warning("Naver credentials not found in environment variables")
        logger.warning("Set NAVER_USERNAME and NAVER_PASSWORD environment variables for authentication")
        return False
    
    logger.info("Authenticating with Naver...")
    
    async with BrowserContext(browser) as context:
        await context.navigate_to("https://nid.naver.com/nidlogin.login")
        await take_screenshot(context, "login_page")
        
        page = await context.get_current_page()
        
        try:
            await page.evaluate(f"""
                () => {{
                    const idInput = document.querySelector('#id');
                    const pwInput = document.querySelector('#pw');
                    
                    if (idInput) {{
                        idInput.value = '{username}';
                        idInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    }}
                    
                    if (pwInput) {{
                        pwInput.value = '{password}';
                        pwInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    }}
                }}
            """)
            
            logger.info("Entered Naver credentials")
            await take_screenshot(context, "credentials_entered")
            
            login_button = await page.query_selector("button.btn_login")
            if login_button:
                await login_button.click()
                logger.info("Clicked login button")
            else:
                logger.warning("Login button not found")
                return False
            
            await asyncio.sleep(3)
            await take_screenshot(context, "after_login")
            
            current_url = page.url
            if "nid.naver.com/nidlogin.login" not in current_url:
                logger.info("Login successful")
                return True
            else:
                logger.warning("Login failed")
                return False
                
        except Exception as e:
            logger.error(f"Error during Naver authentication: {str(e)}")
            return False


def extract_cdp_port():
    """
    Extract the CDP port from running browser processes.
    Returns the most common port number found or a default port if none found.
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


def create_llm(args):
    """
    Create the language model based on command-line arguments.
    """
    if args.use_azure:
        required_vars = [
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_KEY",
            "AZURE_OPENAI_API_VERSION"
        ]
        
        missing_vars = [var for var in required_vars if not os.environ.get(var)]
        if missing_vars:
            logger.error(f"Missing required Azure environment variables: {', '.join(missing_vars)}")
            logger.error("Please set these variables in your environment or .env file")
            sys.exit(1)
            
        logger.info("Using Azure OpenAI with model: %s", args.model)
        return AzureChatOpenAI(
            model=args.model,
            temperature=0.0,
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION"),
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
            api_key=SecretStr(os.environ.get("AZURE_OPENAI_KEY", "")),
        )
    else:
        if not os.environ.get("OPENAI_API_KEY"):
            logger.error("Missing OPENAI_API_KEY environment variable")
            logger.error("Please set this variable in your environment or .env file")
            sys.exit(1)
            
        logger.info("Using OpenAI with model: %s", args.model)
        return ChatOpenAI(
            model=args.model,
            temperature=0.0,
        )


async def main():
    parser = argparse.ArgumentParser(description='Run browser automation with LLM')
    
    parser.add_argument('--cdp-port', type=int, help='CDP port for browser connection (for Devin environment)')
    parser.add_argument('--headless', action='store_true', help='Run browser in headless mode')
    parser.add_argument('--no-headless', dest='headless', action='store_false', help='Run browser in visible mode')
    parser.add_argument('--advanced-mode', action='store_true', default=True, 
                        help='Enable advanced Playwright capabilities (default: True)')
    parser.add_argument('--no-advanced-mode', dest='advanced_mode', action='store_false',
                        help='Disable advanced Playwright capabilities')
    
    parser.add_argument('--model', type=str, default='gpt-4o', help='Model to use (default: gpt-4o)')
    parser.add_argument('--use-azure', action='store_true', help='Use Azure OpenAI instead of OpenAI')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--auth', action='store_true', help='Authenticate with Naver before running the agent')
    parser.add_argument('--screenshots', action='store_true', help='Take screenshots during navigation')
    
    parser.add_argument('--task', type=str, default=DEFAULT_TASK, help='Task to perform')
    
    parser.set_defaults(headless=True)  # Default to headless mode
    
    args = parser.parse_args()
    
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    cdp_port = None
    if args.cdp_port:
        cdp_port = args.cdp_port
    elif not args.headless:  # Only extract CDP port if not in headless mode
        cdp_port = extract_cdp_port()
    
    if cdp_port is not None:
        logger.info(f"Using CDP port: {cdp_port}")
    
    llm = create_llm(args)
    
    try:
        cdp_url = None
        if cdp_port is not None:
            cdp_url = f"http://localhost:{cdp_port}"
            logger.info(f"Converting CDP port {cdp_port} to CDP URL: {cdp_url}")
        
        extra_browser_args = []
        if platform.system() == 'Darwin':  # Mac OS
            extra_browser_args.append('--user-agent=' + 
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
        
        browser_config = BrowserConfig(
            advanced_mode=args.advanced_mode,
            headless=args.headless,
            cdp_url=cdp_url,
            disable_security=True,  # Enable for cross-origin iframe access
            extra_browser_args=extra_browser_args
        )
        
        logger.info(f"Creating browser with advanced_mode={args.advanced_mode}, headless={args.headless}, cdp_url={cdp_url}")
        browser = Browser(config=browser_config)
        
        # Authenticate with Naver if requested
        if args.auth:
            auth_success = await authenticate_naver(browser)
            if not auth_success:
                logger.warning("Naver authentication failed, continuing without authentication")
                logger.warning("Some features may not be accessible without authentication")
        
        custom_task = args.task
        if args.auth and auth_success:
            custom_task = 'Go to https://map.naver.com/p/entry/place/1188320878 and click on the photo to get to the photo categories and then select the 외부 category and then click on the first photo from the 외부 category and verify you are in photo carousel mode'
            logger.info("Using custom task with direct URL: %s", custom_task)
        
        logger.info("Creating agent with task: %s", custom_task)
        agent = Agent(task=custom_task, llm=llm, browser=browser)
        
        if args.screenshots:
            logger.info("Performing manual navigation with screenshots")
            try:
                async with BrowserContext(browser) as context:
                    logger.info("Step 1: Navigating to restaurant page")
                    await context.navigate_to("https://map.naver.com/p/entry/place/1188320878")
                    await asyncio.sleep(3)
                    await take_screenshot(context, "step1_restaurant_page")
                    
                    logger.info("Step 2: Finding and clicking on photo tab")
                    page = await context.get_current_page()
                    photo_tab = await context.get_element_by_korean_text("사진", retry_count=3, wait_time=1000)
                    if photo_tab:
                        logger.info("Found photo tab by Korean text")
                        await page.evaluate("(element) => element.click()", photo_tab)
                        await asyncio.sleep(3)
                        await take_screenshot(context, "step2_photo_tab")
                    else:
                        logger.warning("Could not find photo tab by Korean text")
                    
                    logger.info("Step 3: Finding and clicking on '외부' category")
                    exterior_category = await context.get_element_by_korean_text("외부", retry_count=3, wait_time=1000)
                    if exterior_category:
                        logger.info("Found '외부' category by Korean text")
                        await page.evaluate("(element) => element.click()", exterior_category)
                        await asyncio.sleep(3)
                        await take_screenshot(context, "step3_exterior_category")
                    else:
                        logger.warning("Could not find '외부' category by Korean text")
                    
                    logger.info("Step 4: Finding and clicking on first photo")
                    photo_elements = await context.get_naver_photo_elements(deep_search=True, retry_count=3, wait_time=1000)
                    if photo_elements and len(photo_elements) > 0:
                        logger.info(f"Found {len(photo_elements)} photo elements")
                        await photo_elements[0].click()
                        await asyncio.sleep(3)
                        await take_screenshot(context, "step4_photo_carousel")
                        
                        logger.info("Step 5: Verifying carousel mode")
                        next_button = await page.query_selector("button[aria-label*='다음']")
                        prev_button = await page.query_selector("button[aria-label*='이전']")
                        if next_button or prev_button:
                            logger.info("✅ Successfully verified photo carousel mode")
                            await take_screenshot(context, "step5_verified_carousel")
                        else:
                            logger.warning("❌ Could not verify photo carousel mode")
                    else:
                        logger.warning("No photo elements found")
                
                logger.info("Manual navigation with screenshots completed")
            except Exception as e:
                logger.error(f"Error during manual navigation: {str(e)}")
                logger.info("Continuing with agent-based navigation")
        
        logger.info("Running agent...")
        await agent.run()
        
        logger.info("Agent run completed successfully")
    except Exception as e:
        logger.error("Error running agent: %s", str(e))
        raise


if __name__ == '__main__':
    asyncio.run(main())
